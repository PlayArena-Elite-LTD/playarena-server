from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

from django.db import migrations, models
import django.core.validators


CENT = Decimal("0.01")
PLATFORM_PERCENT = Decimal("10.00")


def _allocate(registrations, total, gross):
    if not gross:
        return {registration.pk: Decimal("0.00") for registration in registrations}

    rows = []
    allocated = Decimal("0.00")
    for registration in registrations:
        exact = Decimal(registration.amount_paid) * total / gross
        amount = exact.quantize(CENT, rounding=ROUND_DOWN)
        rows.append([registration, amount, exact - amount])
        allocated += amount

    remaining_cents = int((total - allocated) / CENT)
    rows.sort(key=lambda row: (-row[2], row[0].pk))
    for index in range(remaining_cents):
        rows[index][1] += CENT
    return {registration.pk: amount for registration, amount, _ in rows}


def configure_existing_tournaments(apps, schema_editor):
    Tournament = apps.get_model("matches", "Tournament")
    TournamentRegistration = apps.get_model("matches", "TournamentRegistration")
    TournamentFeeSettlement = apps.get_model("matches", "TournamentFeeSettlement")
    database = schema_editor.connection.alias

    Tournament.objects.using(database).all().update(platform_fee_percent=PLATFORM_PERCENT)
    TournamentRegistration.objects.using(database).filter(
        status="REGISTERED",
        tournament__fee_settlement__isnull=True,
    ).update(
        platform_fee=Decimal("0.00"),
        organiser_fee=Decimal("0.00"),
        prize_contribution=models.F("amount_paid"),
    )

    settlements = TournamentFeeSettlement.objects.using(database).select_related(
        "tournament"
    )
    for settlement in settlements.iterator():
        if settlement.status != "RESERVED":
            settlement.organiser_fee = Decimal("0.00")
            settlement.organiser_fee_percent = Decimal("0.00")
            settlement.save(
                using=database,
                update_fields=["organiser_fee", "organiser_fee_percent"],
            )
            continue

        registrations = list(
            TournamentRegistration.objects.using(database)
            .filter(
                tournament_id=settlement.tournament_id,
                status="REGISTERED",
            )
            .order_by("pk")
        )
        gross = Decimal(settlement.gross_pool)
        platform_fee = (gross * PLATFORM_PERCENT / Decimal("100")).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        post_platform_pool = gross - platform_fee
        organiser_percent = Decimal(settlement.tournament.organiser_fee_percent)
        organiser_fee = (
            post_platform_pool * organiser_percent / Decimal("100")
        ).quantize(CENT, rounding=ROUND_HALF_UP)
        platform_allocations = _allocate(registrations, platform_fee, gross)
        organiser_allocations = _allocate(registrations, organiser_fee, gross)

        for registration in registrations:
            registration.platform_fee = platform_allocations[registration.pk]
            registration.organiser_fee = organiser_allocations[registration.pk]
            registration.prize_contribution = (
                Decimal(registration.amount_paid)
                - registration.platform_fee
                - registration.organiser_fee
            )
            registration.save(
                using=database,
                update_fields=[
                    "platform_fee",
                    "organiser_fee",
                    "prize_contribution",
                ],
            )

        settlement.platform_fee = platform_fee
        settlement.fee_percent = PLATFORM_PERCENT
        settlement.organiser_fee = organiser_fee
        settlement.organiser_fee_percent = organiser_percent
        settlement.net_prize_pool = post_platform_pool - organiser_fee
        settlement.save(
            using=database,
            update_fields=[
                "platform_fee",
                "fee_percent",
                "organiser_fee",
                "organiser_fee_percent",
                "net_prize_pool",
            ],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("matches", "0027_tournament_admin_fee_range"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="organiser_fee_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("10.00"),
                help_text="Organiser share percentage of the pool remaining after the platform fee.",
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(10),
                ],
            ),
        ),
        migrations.AddField(
            model_name="tournamentfeesettlement",
            name="organiser_fee",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=16,
            ),
        ),
        migrations.AddField(
            model_name="tournamentfeesettlement",
            name="organiser_fee_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("10.00"),
                max_digits=5,
            ),
        ),
        migrations.AddField(
            model_name="tournamentregistration",
            name="organiser_fee",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Organiser earnings allocated from this entry.",
                max_digits=10,
            ),
        ),
        migrations.AlterField(
            model_name="tournament",
            name="platform_fee_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("10.00"),
                help_text="Fixed PlayArena platform fee percentage.",
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(10),
                    django.core.validators.MaxValueValidator(10),
                ],
            ),
        ),
        migrations.RunPython(configure_existing_tournaments, migrations.RunPython.noop),
    ]
