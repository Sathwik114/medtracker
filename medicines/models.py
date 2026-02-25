from django.db import models
from django.utils import timezone


class Medicine(models.Model):
    REGULAR = 'regular'
    EMERGENCY = 'emergency'

    TYPE_CHOICES = [
        (REGULAR, 'Regular'),
        (EMERGENCY, 'Emergency')
    ]

    SCHEDULE_TIMES = {
        'morning': 8,
        'afternoon': 13,
        'evening': 18,
        'night': 21,
    }

    SCHEDULE_LABELS = {
        'morning': '🌅 Morning (8:00)',
        'afternoon': '☀️ Afternoon (13:00)',
        'evening': '🌆 6 PM (18:00)',
        'night': '🌙 Night (21:00)',
    }

    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    total_tablets = models.PositiveIntegerField(default=0)
    remaining_tablets = models.PositiveIntegerField(default=0)
    tablets_per_dose = models.PositiveIntegerField(default=1)

    medicine_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=REGULAR
    )

    schedules = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    # ---------------- STOCK STATUS ----------------
    def stock_status(self):
        if self.remaining_tablets == 0:
            return 'finished'
        elif self.remaining_tablets <= 5:
            return 'low'
        return 'ok'

    # ---------------- NEXT DOSE CALCULATION ----------------
    def next_dose_time(self):
        if not self.schedules:
            return '—'

        current_hour = timezone.localtime().hour

        sorted_schedules = sorted(
            self.schedules,
            key=lambda s: self.SCHEDULE_TIMES.get(s, 0)
        )

        next_schedule = next(
            (s for s in sorted_schedules
             if self.SCHEDULE_TIMES.get(s, 0) > current_hour),
            sorted_schedules[0]
        )

        return self.SCHEDULE_LABELS.get(next_schedule, '—')

    # ---------------- SAFE REFILL METHOD ----------------
    def add_tablets(self, quantity, entry_type='refill', note=""):
        if quantity <= 0:
            return

        self.remaining_tablets += quantity
        self.total_tablets += quantity
        self.save()

        MedicineHistory.objects.create(
            medicine=self,
            medicine_name=self.name,
            entry_type=entry_type,
            tablets=quantity,
            price=self.price * quantity if entry_type == MedicineHistory.PURCHASE else 0,
            note=note
        )

    # ---------------- SAFE DOSE METHOD ----------------
    def take_dose(self, schedule_key):
        today = timezone.localdate()

        if self.remaining_tablets < self.tablets_per_dose:
            return False

        if DoseLog.objects.filter(
            medicine=self,
            schedule_key=schedule_key,
            date=today
        ).exists():
            return False

        self.remaining_tablets -= self.tablets_per_dose
        self.save()

        DoseLog.objects.create(
            medicine=self,
            schedule_key=schedule_key,
            date=today
        )

        MedicineHistory.objects.create(
            medicine=self,
            medicine_name=self.name,
            entry_type=MedicineHistory.DOSE,
            tablets=self.tablets_per_dose,
            price=0,
            note=f"Auto dose taken ({schedule_key})"
        )

        return True

    class Meta:
        ordering = ['-created_at']


# --------------------------------------------------
# Tracks auto-applied doses per day
# --------------------------------------------------
class DoseLog(models.Model):
    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.CASCADE,
        related_name='dose_logs'
    )
    schedule_key = models.CharField(max_length=20)
    date = models.DateField()

    class Meta:
        unique_together = ('medicine', 'schedule_key', 'date')

    def __str__(self):
        return f"{self.medicine.name} - {self.schedule_key} - {self.date}"


# --------------------------------------------------
# HISTORY TABLE
# --------------------------------------------------
class MedicineHistory(models.Model):

    PURCHASE = 'purchase'
    REFILL = 'refill'
    DOSE = 'dose'

    TYPE_CHOICES = [
        (PURCHASE, 'Purchase'),
        (REFILL, 'Refill'),
        (DOSE, 'Auto Dose'),
    ]

    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='history'
    )

    medicine_name = models.CharField(max_length=200)
    entry_type = models.CharField(max_length=20, choices=TYPE_CHOICES)

    tablets = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.medicine_name} - {self.entry_type} - {self.created_at.strftime('%d %b %Y')}"

    class Meta:
        ordering = ['-created_at']


# --------------------------------------------------
# EXPENSES
# --------------------------------------------------
class Expense(models.Model):

    CATEGORY_CHOICES = [
        ('medicine', '💊 Medicine'),
        ('consultation', '🏥 Doctor Consultation'),
        ('lab', '🧪 Lab Test'),
        ('equipment', '🩺 Medical Equipment'),
        ('transport', '🚗 Transport'),
        ('other', '📦 Other'),
    ]

    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)  # ← NEW FIELD

    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default='other'
    )

    note = models.TextField(blank=True)
    expense_date = models.DateField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - ₹{self.amount} - {self.expense_date}"

    def total_amount(self):
        return self.amount * self.quantity

    class Meta:
        ordering = ['-expense_date', '-created_at']