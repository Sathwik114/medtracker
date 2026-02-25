from django.core.management.base import BaseCommand
from django.utils import timezone
from medicines.models import Medicine, DoseLog, MedicineHistory


SCHEDULE_HOURS = {
    'morning': (5, 11),
    'afternoon': (11, 16),
    'evening': (16, 20),
    'night': (20, 29),  # 20:00 to next day 05:00
}


class Command(BaseCommand):
    help = 'Auto apply doses for scheduled medicines based on current time'

    def handle(self, *args, **kwargs):
        now = timezone.localtime()
        current_hour = now.hour
        today = now.date()

        # Determine current time slot
        current_slot = None
        if 5 <= current_hour < 11:
            current_slot = 'morning'
        elif 11 <= current_hour < 16:
            current_slot = 'afternoon'
        elif 16 <= current_hour < 20:
            current_slot = 'evening'
        elif current_hour >= 20 or current_hour < 5:
            current_slot = 'night'

        if not current_slot:
            self.stdout.write("No active time slot.")
            return

        medicines = Medicine.objects.filter(medicine_type='regular')
        applied = 0

        for med in medicines:
            if current_slot not in (med.schedules or []):
                continue

            # Check if dose already applied today for this slot
            already_done = DoseLog.objects.filter(
                medicine=med,
                schedule_key=current_slot,
                date=today
            ).exists()

            if already_done:
                continue

            # Apply dose
            dose = med.tablets_per_dose
            old_remaining = med.remaining_tablets
            med.remaining_tablets = max(0, old_remaining - dose)
            med.save()

            # Log it
            DoseLog.objects.create(medicine=med, schedule_key=current_slot, date=today)

            if med.remaining_tablets == 0:
                note = f"Auto dose ({current_slot}) — Medicine FINISHED. Please refill."
            elif med.remaining_tablets <= 5:
                note = f"Auto dose ({current_slot}) — Only {med.remaining_tablets} tablets left! ⚠️"
            else:
                note = f"Auto dose ({current_slot}) — {dose} tablet(s) taken. {med.remaining_tablets} remaining."

            MedicineHistory.objects.create(
                medicine=med,
                medicine_name=med.name,
                entry_type='dose',
                tablets=dose,
                price=0,
                note=note,
            )

            applied += 1
            self.stdout.write(f"✅ {med.name}: {note}")

        self.stdout.write(f"\nDone. {applied} dose(s) applied for slot: {current_slot}")
