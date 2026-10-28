from decimal import Decimal

from django.db import migrations, models

# Built-ins that were seeded with an empty config and so silently read as weight-metered:
# a priced CNC mill rejected every manual-usage log. Frozen here on purpose -- a migration
# must not import live code that may change after it ships.
EXPLICIT_CONFIGS = {
    "cnc_mill": {"metering_unit": "minutes", "requires_booking": True},
    "pcb_mill": {"metering_unit": "minutes", "requires_booking": False},
    "other": {"metering_unit": "minutes", "requires_booking": False},
}


def _makerspaces_metering_by_weight(apps, machine_type):
    """Spaces whose pools or per-unit price already treat this type as weight-metered."""
    Pool = apps.get_model("machines", "MachineConsumablePool")
    Pricing = apps.get_model("machines", "MakerspaceMachineTypePricing")
    pooled = Pool.objects.filter(is_active=True).filter(
        models.Q(machine_type_id=machine_type.pk) | models.Q(machine__machine_type_id=machine_type.pk)
    ).values_list("makerspace_id", flat=True)
    priced = Pricing.objects.filter(machine_type_id=machine_type.pk, rate_per_unit__gt=0).values_list(
        "makerspace_id", flat=True
    )
    return set(pooled) | set(priced)


def name_the_unit_of_unconfigured_builtins(apps, schema_editor):
    MachineType = apps.get_model("machines", "MachineType")
    Pricing = apps.get_model("machines", "MakerspaceMachineTypePricing")
    for machine_type in MachineType.objects.filter(makerspace__isnull=True, slug__in=EXPLICIT_CONFIGS):
        config = dict(machine_type.capability_config or {})
        if "metering_unit" in config:
            continue  # A deployment that already named a unit keeps it.
        # Until now the server metered these types by weight. A space already running them
        # that way (gram pools, a per-gram price) keeps weight through an override, so its
        # pools are not stranded and its rate is not reread as a per-minute price.
        keep_weight = _makerspaces_metering_by_weight(apps, machine_type)
        for makerspace_id in keep_weight:
            row, _ = Pricing.objects.get_or_create(makerspace_id=makerspace_id, machine_type_id=machine_type.pk)
            if row.metering_unit_override is None:
                Pricing.objects.filter(pk=row.pk).update(metering_unit_override="weight")
        for key, value in EXPLICIT_CONFIGS[machine_type.slug].items():
            config.setdefault(key, value)
        MachineType.objects.filter(pk=machine_type.pk).update(capability_config=config)
        # 0023 gave these rows the 20 g printer threshold because the unit read as weight;
        # in minutes that would be twenty free minutes nobody chose.
        Pricing.objects.filter(machine_type_id=machine_type.pk, free_below_quantity=Decimal("20")).exclude(
            makerspace_id__in=keep_weight
        ).update(free_below_quantity=Decimal("0"))


class Migration(migrations.Migration):

    dependencies = [
        ("machines", "0023_manual_usage_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="makerspacemachinetypepricing",
            name="metering_unit_override",
            field=models.CharField(blank=True, choices=[("minutes", "Minutes"), ("weight", "Weight"), ("volume", "Volume"), ("length", "Length"), ("count", "Count")], max_length=12, null=True),
        ),
        migrations.AddField(
            model_name="makerspacemachinetypepricing",
            name="requires_booking_override",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="makerspacemachinetypepricing",
            name="uses_consumables_override",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.RunPython(name_the_unit_of_unconfigured_builtins, migrations.RunPython.noop),
    ]
