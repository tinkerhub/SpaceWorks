import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("inventory", "0009_inventoryproduct_image_key"), ("makerspaces", "0071_makerspace_checkin_api_settings")]
AFTER = [("inventory", "0011_item_code_constraints")]


@pytest.mark.django_db(transaction=True)
def test_existing_data_gets_prefixes_codes_and_letters_without_losing_categories():
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(BEFORE)
        old = executor.loader.project_state(BEFORE).apps
        Makerspace = old.get_model("makerspaces", "Makerspace")
        Category = old.get_model("inventory", "Category")
        Product = old.get_model("inventory", "InventoryProduct")
        kochi = Makerspace.objects.create(name="Tinkerspace Kochi", slug="mig-kochi")
        clash = Makerspace.objects.create(name="Tinkerspace Kerala", slug="mig-kerala")
        legacy = {}
        for order, name in enumerate(
            ["SBCs", "Microcontrollers", "Microprocessors", "Sensors", "Actuators", "Cables", "Accessories"]
        ):
            legacy[name] = Category.objects.create(
                makerspace=kochi, name=name, slug=name.lower(), display_order=order
            )
        displays = Category.objects.create(makerspace=kochi, name="Displays", slug="displays")
        quantities = dict(total_quantity=1, available_quantity=1)
        uno = Product.objects.create(makerspace=kochi, name="UNO", category=legacy["Microcontrollers"], **quantities)
        esp = Product.objects.create(makerspace=kochi, name="ESP32", category=legacy["Microcontrollers"], **quantities)
        pi = Product.objects.create(makerspace=kochi, name="Pi", category=legacy["SBCs"], **quantities)
        loose = Product.objects.create(makerspace=kochi, name="Loose", **quantities)

        executor = MigrationExecutor(connection)
        executor.migrate(AFTER)
        new = executor.loader.project_state(AFTER).apps
        Makerspace = new.get_model("makerspaces", "Makerspace")
        Category = new.get_model("inventory", "Category")
        Product = new.get_model("inventory", "InventoryProduct")

        assert Makerspace.objects.get(pk=kochi.pk).item_code_prefix == "TK"
        assert Makerspace.objects.get(pk=clash.pk).item_code_prefix == "TE"
        codes = dict(Category.objects.filter(makerspace=kochi.pk).values_list("slug", "code"))
        assert codes["microcontrollers"] == "MCU"
        assert codes["sensors"] == "SNS"
        assert codes["accessories"] == "MOD"
        assert codes["cables"] == "CBL"
        assert codes["displays"] == "DSP"
        assert codes["sbcs"] == "" and codes["microprocessors"] == ""
        assert sorted(code for code in codes.values() if code) == sorted(
            ["MCU", "SNS", "ACT", "PWR", "NET", "MOD", "CBL", "CON", "DSP", "DRV"]
        )
        assert Category.objects.filter(pk=displays.pk).exists()
        letters = dict(Product.objects.values_list("name", "code_letter"))
        assert [letters["UNO"], letters["ESP32"], letters["Pi"], letters["Loose"]] == ["A", "B", "A", ""]
        assert Category.objects.get(pk=legacy["Microcontrollers"].pk).code_sequence == 2
        assert {uno.pk, esp.pk, pi.pk, loose.pk} <= set(Product.objects.values_list("pk", flat=True))

        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
