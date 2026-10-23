from threading import Barrier, Thread

import pytest
from django.db import close_old_connections
from rest_framework.test import APIClient

from apps.admin_api.bulk_import_rows import find_category
from apps.inventory.categories import STANDARD_CATEGORIES
from apps.inventory.item_codes import letter_for_index
from apps.inventory.models import Category, InventoryProduct
from apps.makerspaces.item_code_prefix import derive_prefix
from apps.makerspaces.models import Makerspace
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db


def category(makerspace, code):
    return Category.objects.get(makerspace=makerspace, code=code)


def space(name, slug):
    return Makerspace.objects.create(name=name, slug=slug)


def test_letters_run_like_spreadsheet_columns():
    assert [letter_for_index(i) for i in (0, 1, 25, 26, 27, 51, 52, 701, 702)] == [
        "A", "B", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA",
    ]


@pytest.mark.parametrize(
    ("name", "taken", "expected"),
    [
        ("Tinkerspace Kochi", set(), "TK"),
        ("Tinkerspace Calicut", {"TK"}, "TC"),
        # A clash keeps the first letter and moves the second through the rest of the name.
        ("Tinkerspace Chennai", {"TK", "TC"}, "TH"),
        ("Tinker Space Kochi", set(), "TK"),
        ("Fablab", set(), "FA"),
        ("", set(), "SW"),
    ],
)
def test_prefix_defaults_from_the_name(name, taken, expected):
    assert derive_prefix(name, taken) == expected


def test_new_makerspaces_get_unique_prefixes_and_standard_categories():
    kochi = space("Tinkerspace Kochi", "tinkerspace-kochi")
    calicut = space("Tinkerspace Calicut", "tinkerspace-calicut")
    chennai = space("Tinkerspace Chennai", "tinkerspace-chennai")
    chennai_two = space("Tinkerspace Chennai", "tinkerspace-chennai-2")

    assert [kochi.item_code_prefix, calicut.item_code_prefix] == ["TK", "TC"]
    assert chennai.item_code_prefix == "TH"
    assert chennai_two.item_code_prefix == "TE"
    codes = list(
        Category.objects.filter(makerspace=calicut)
        .exclude(code="")
        .order_by("display_order")
        .values_list("code", flat=True)
    )
    assert codes == [code for code, _name in STANDARD_CATEGORIES]


def test_products_get_codes_in_order_and_letters_are_never_reused():
    calicut = space("Tinkerspace Calicut", "codes-calicut")
    mcu = category(calicut, "MCU")
    esp32 = make_product(calicut, "ESP32 DevKit", category=mcu)
    uno = make_product(calicut, "Arduino UNO", category=mcu)
    mpu = make_product(calicut, "MPU6050", category=category(calicut, "SNS"))

    assert [esp32.item_code, uno.item_code, mpu.item_code] == [
        "TC-MCU-A", "TC-MCU-B", "TC-SNS-A",
    ]
    uno.delete()
    nano = make_product(calicut, "Arduino Nano", category=mcu)
    assert nano.item_code == "TC-MCU-C"


def test_moving_category_issues_a_new_letter_and_resaves_keep_it():
    makerspace = space("Tinkerspace Calicut", "codes-move")
    relay = make_product(makerspace, "Relay module", category=category(makerspace, "MOD"))
    assert relay.item_code == "TC-MOD-A"

    relay.total_quantity = 12
    relay.save(update_fields=["total_quantity"])
    relay.refresh_from_db()
    assert relay.item_code == "TC-MOD-A"

    reloaded = InventoryProduct.objects.get(pk=relay.pk)
    reloaded.category = category(makerspace, "DRV")
    reloaded.save()
    assert reloaded.item_code == "TC-DRV-A"

    reloaded.category = None
    reloaded.save()
    assert reloaded.code_letter == "" and reloaded.item_code == ""


def test_deferred_category_save_does_not_reissue_a_letter():
    makerspace = space("Tinkerspace Calicut", "codes-deferred")
    product = make_product(makerspace, "OLED", category=category(makerspace, "DSP"))
    partial = InventoryProduct.objects.only("id", "name", "code_letter").get(pk=product.pk)
    partial.save()
    product.refresh_from_db()
    assert product.item_code == "TC-DSP-A"


def test_prefix_and_category_code_changes_relabel_every_item():
    makerspace = space("Tinkerspace Calicut", "codes-relabel")
    mcu = category(makerspace, "MCU")
    product = make_product(makerspace, "ESP32", category=mcu)
    makerspace.item_code_prefix = "TCL"
    makerspace.save(update_fields=["item_code_prefix"])
    mcu.code = "MCX"
    mcu.save(update_fields=["code"])

    product = InventoryProduct.objects.select_related("makerspace", "category").get(pk=product.pk)
    assert product.item_code == "TCL-MCX-A"


def test_uncoded_category_holds_a_letter_until_it_gets_a_code():
    makerspace = space("Tinkerspace Calicut", "codes-uncoded")
    tools = Category.objects.create(makerspace=makerspace, name="Hand tools", slug="hand-tools")
    pliers = make_product(makerspace, "Pliers", category=tools)
    assert pliers.code_letter == "A" and pliers.item_code == ""

    tools.code = "TLS"
    tools.save(update_fields=["code"])
    pliers.refresh_from_db()
    assert pliers.item_code == "TC-TLS-A"


@pytest.mark.django_db(transaction=True)
def test_concurrent_creates_in_one_category_get_distinct_letters():
    makerspace = space("Tinkerspace Calicut", "codes-race")
    mcu = category(makerspace, "MCU")
    barrier = Barrier(4)
    errors = []

    def create(index):
        close_old_connections()
        try:
            barrier.wait(5)
            make_product(makerspace, f"Board {index}", category=mcu)
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [Thread(target=create, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert errors == []
    letters = sorted(
        InventoryProduct.objects.filter(category=mcu).values_list("code_letter", flat=True)
    )
    assert letters == ["A", "B", "C", "D"]


def test_staff_api_exposes_codes_and_validates_category_codes():
    makerspace = make_space("codes-api")
    admin = make_member("codes-api-admin", makerspace)
    client = authenticated_client(admin)
    mcu = category(makerspace, "MCU")

    created = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory",
        {"name": "ESP32", "total_quantity": 3, "available_quantity": 3, "category": mcu.id},
        format="json",
    )
    assert created.status_code == 201
    assert created.data["item_code"] == f"{makerspace.item_code_prefix}-MCU-A"

    listed = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory",
        {"q": created.data["item_code"].lower()},
    )
    assert [row["name"] for row in listed.data["results"]] == ["ESP32"]

    bad = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/categories",
        {"name": "Tools", "code": "t00ls"},
        format="json",
    )
    assert bad.status_code == 400 and "code" in bad.data
    duplicate = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/categories",
        {"name": "Boards", "code": "mcu"},
        format="json",
    )
    assert duplicate.status_code == 400 and "MCU" in str(duplicate.data["code"])
    good = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/categories",
        {"name": "Hand tools", "code": "tls"},
        format="json",
    )
    assert good.status_code == 201 and good.data["code"] == "TLS"


def test_staff_can_override_the_prefix_but_not_take_anothers():
    kochi = space("Tinkerspace Kochi", "prefix-kochi")
    calicut = space("Tinkerspace Calicut", "prefix-calicut")
    admin = make_member("prefix-calicut-admin", calicut)
    client = authenticated_client(admin)
    url = f"/api/v1/admin/makerspaces/{calicut.id}"

    taken = client.patch(url, {"item_code_prefix": kochi.item_code_prefix}, format="json")
    assert taken.status_code == 400
    assert "already used" in str(taken.data["item_code_prefix"])

    changed = client.patch(url, {"item_code_prefix": "clt"}, format="json")
    assert changed.status_code == 200 and changed.data["item_code_prefix"] == "CLT"

    reset = client.patch(url, {"item_code_prefix": ""}, format="json")
    assert reset.status_code == 200 and reset.data["item_code_prefix"] == "TC"


def test_public_catalogue_shows_item_and_category_codes():
    makerspace = space("Tinkerspace Calicut", "codes-public")
    make_product(makerspace, "ESP32", category=category(makerspace, "MCU"))
    public = APIClient()
    products = public.get(f"/api/v1/public/{makerspace.slug}/inventory/")
    assert products.status_code == 200
    assert products.data["results"][0]["item_code"] == "TC-MCU-A"
    by_code = public.get(f"/api/v1/public/{makerspace.slug}/inventory/", {"q": "MCU-A"})
    assert [row["name"] for row in by_code.data["results"]] == ["ESP32"]
    categories = public.get(f"/api/v1/public/{makerspace.slug}/inventory/categories/")
    assert [row["code"] for row in categories.data] == ["MCU"]


def test_bulk_import_resolves_a_category_by_code_or_name():
    makerspace = space("Tinkerspace Calicut", "codes-bulk")
    assert find_category(makerspace, "mcu").code == "MCU"
    assert find_category(makerspace, "Sensors").code == "SNS"
    assert find_category(makerspace, "Nope") is None


def test_a_stale_category_save_does_not_rewind_the_letter_counter():
    makerspace = space("Tinkerspace Calicut", "codes-stale")
    stale = category(makerspace, "SNS")
    make_product(makerspace, "DHT22", category=stale)
    stale.name = "Sensors & probes"
    stale.save()  # loaded before the letter above was issued

    stale.refresh_from_db()
    assert stale.code_sequence == 1
    assert make_product(makerspace, "PIR", category=stale).item_code == "TC-SNS-B"


def test_a_rewound_counter_still_never_reissues_a_letter():
    makerspace = space("Tinkerspace Calicut", "codes-rewound")
    pwr = category(makerspace, "PWR")
    make_product(makerspace, "LM2596", category=pwr)
    Category.objects.filter(pk=pwr.pk).update(code_sequence=0)

    assert make_product(makerspace, "XL6009", category=pwr).item_code == "TC-PWR-B"


def test_code_search_adds_to_name_search_rather_than_replacing_it():
    makerspace = make_space("codes-union")
    admin = make_member("codes-union-admin", makerspace)
    usb = Category.objects.create(makerspace=makerspace, name="USB gear", slug="usb-gear", code="USB")
    make_product(makerspace, "Hub", category=usb)
    make_product(makerspace, "Hub 2", category=usb)
    make_product(makerspace, "Hub 3", category=usb)  # USB-C
    make_product(makerspace, "USB-C cable")

    listed = authenticated_client(admin).get(
        f"/api/v1/admin/makerspace/{makerspace.id}/inventory", {"q": "USB-C"}
    )
    assert sorted(row["name"] for row in listed.data["results"]) == ["Hub 3", "USB-C cable"]


def test_an_importing_makerspace_is_not_seeded_with_standard_categories():
    importing = Makerspace.objects.create(
        name="Imported space",
        slug="codes-importing",
        lifecycle_state=Makerspace.LifecycleState.IMPORTING,
    )
    assert not Category.objects.filter(makerspace=importing).exists()
