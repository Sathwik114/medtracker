from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum
import datetime
from groq import Groq
from django.conf import settings
from django.http import JsonResponse
from .models import Medicine
from .models import MedicineHistory, Expense, DoseLog
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from django.http import HttpResponse


# ─────────────────────────────────────────────────────────────
# HELPER: Detect Current Slot
# ─────────────────────────────────────────────────────────────
def get_current_slot():
    now_hour = timezone.localtime().hour

    if 5 <= now_hour < 11:
        return 'morning'
    elif 11 <= now_hour < 16:
        return 'afternoon'
    elif 16 <= now_hour < 20:
        return 'evening'
    else:
        return 'night'


# ─────────────────────────────────────────────────────────────
# AUTO DOSE SYSTEM
# ─────────────────────────────────────────────────────────────
def run_auto_dose():
    now = timezone.localtime()
    today = now.date()
    current_slot = get_current_slot()

    medicines = Medicine.objects.filter(medicine_type='regular')

    for med in medicines:

        if current_slot not in (med.schedules or []):
            continue

        already_taken = DoseLog.objects.filter(
            medicine=med,
            schedule_key=current_slot,
            date=today
        ).exists()

        if already_taken:
            continue

        if med.remaining_tablets <= 0:
            continue

        dose = med.tablets_per_dose
        med.remaining_tablets = max(0, med.remaining_tablets - dose)
        med.save()

        DoseLog.objects.create(
            medicine=med,
            schedule_key=current_slot,
            date=today
        )

        # History Note
        if med.remaining_tablets == 0:
            note = f"Auto dose ({current_slot}) — Medicine FINISHED."
        elif med.remaining_tablets <= 5:
            note = f"Auto dose ({current_slot}) — Only {med.remaining_tablets} left!"
        else:
            note = f"Auto dose ({current_slot}) — {dose} tablet(s) taken."

        MedicineHistory.objects.create(
            medicine=med,
            medicine_name=med.name,
            entry_type='dose',
            tablets=dose,
            price=0,
            note=note,
        )


# ─────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────
def dashboard(request):

    run_auto_dose()

    medicines = Medicine.objects.all().order_by("-created_at")
    selected_slot = request.GET.get('slot')

    # ================= FILTER BY SLOT =================
    if selected_slot:
        filtered_regular = [
            med for med in medicines.filter(medicine_type='regular')
            if selected_slot in (med.schedules or [])
        ]

        emergency_meds = medicines.filter(medicine_type='emergency')
        medicines = list(filtered_regular) + list(emergency_meds)
        regular_meds = filtered_regular

    else:
        regular_meds = medicines.filter(medicine_type='regular')
        emergency_meds = medicines.filter(medicine_type='emergency')

    # ================= COUNTS =================
    total_meds = Medicine.objects.count()
    total_regular = Medicine.objects.filter(medicine_type='regular').count()
    total_emergency = Medicine.objects.filter(medicine_type='emergency').count()
    low_stock = Medicine.objects.filter(
        remaining_tablets__gt=0,
        remaining_tablets__lte=5
    ).count()
    finished = Medicine.objects.filter(
        remaining_tablets=0
    ).count()

    # ================= EMERGENCY DOSES TODAY =================
    today = timezone.localdate()
    emergency_doses_today = MedicineHistory.objects.filter(
        entry_type='dose',
        note__icontains='emergency dose',
        created_at__date=today
    ).count()

    context = {
        'medicines': medicines,
        'regular_meds': regular_meds,
        'emergency_meds': emergency_meds,
        'selected_slot': selected_slot,
        'total_meds': total_meds,
        'total_regular': total_regular,
        'total_emergency': total_emergency,
        'low_stock': low_stock,
        'finished': finished,
        'emergency_doses_today': emergency_doses_today,
    }

    return render(request, 'medicines/dashboard.html', context)


# ─────────────────────────────────────────────────────────────
# ADD MEDICINE
# ─────────────────────────────────────────────────────────────
def add_medicine(request):

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()

        try:
            price = float(request.POST.get('price', 0) or 0)
            total_tablets = int(request.POST.get('total_tablets', 0) or 0)
            tablets_per_dose = int(request.POST.get('tablets_per_dose', 1) or 1)
        except ValueError:
            messages.error(request, "Invalid numeric input.")
            return redirect('add_medicine')

        medicine_type = request.POST.get('medicine_type', 'regular')
        schedules = request.POST.getlist('schedules')

        if not name:
            messages.error(request, "Medicine name is required.")
            return redirect('add_medicine')

        # If same medicine already exists (by name and type), treat this as a refill/update
        existing = Medicine.objects.filter(
            name__iexact=name,
            medicine_type=medicine_type
        ).first()

        if existing:
            # Update basic fields
            existing.price = price
            existing.tablets_per_dose = tablets_per_dose
            # Only overwrite schedules for regular medicines
            if medicine_type == 'regular':
                existing.schedules = schedules

            # Safely add new tablets and record history as a refill
            if total_tablets > 0:
                existing.add_tablets(
                    quantity=total_tablets,
                    entry_type=MedicineHistory.REFILL,
                    note=f"Refill from Add Medicine form (+{total_tablets} tablets)."
                )
            else:
                existing.save()

            messages.success(request, f"{name} already exists – updated with new stock.")
        else:
            med = Medicine.objects.create(
                name=name,
                price=price,
                total_tablets=total_tablets,
                remaining_tablets=total_tablets,
                tablets_per_dose=tablets_per_dose,
                medicine_type=medicine_type,
                schedules=schedules
            )

            MedicineHistory.objects.create(
                medicine=med,
                medicine_name=med.name,
                entry_type='purchase',
                tablets=total_tablets,
                price=price,
                note=f"First purchase — {total_tablets} tablets."
            )

            messages.success(request, f"{name} added successfully!")

        return redirect('dashboard')

    return render(request, 'medicines/add_medicine.html')


# ─────────────────────────────────────────────────────────────
# EDIT MEDICINE
# ─────────────────────────────────────────────────────────────
def edit_medicine(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk)

    if request.method == 'POST':

        old_remaining = medicine.remaining_tablets

        try:
            medicine.name = request.POST.get('name', '').strip()
            medicine.price = float(request.POST.get('price', 0) or 0)
            medicine.total_tablets = int(request.POST.get('total_tablets', 0) or 0)
            medicine.remaining_tablets = int(request.POST.get('remaining_tablets', 0) or 0)
            medicine.tablets_per_dose = int(request.POST.get('tablets_per_dose', 1) or 1)
        except ValueError:
            messages.error(request, "Invalid numeric input.")
            return redirect('edit_medicine', pk=pk)

        medicine.medicine_type = request.POST.get('medicine_type', 'regular')
        medicine.schedules = request.POST.getlist('schedules')

        if medicine.remaining_tablets < 0:
            messages.error(request, "Remaining tablets cannot be negative.")
            return redirect('edit_medicine', pk=pk)

        medicine.save()

        increase = medicine.remaining_tablets - old_remaining

        if increase > 0:
            MedicineHistory.objects.create(
                medicine=medicine,
                medicine_name=medicine.name,
                entry_type='refill',
                tablets=increase,
                price=medicine.price,
                note=f"Refilled +{increase} tablets."
            )

        messages.success(request, f"{medicine.name} updated successfully!")
        return redirect('dashboard')

    return render(request, 'medicines/edit_medicine.html', {'medicine': medicine})


# ─────────────────────────────────────────────────────────────
# DELETE MEDICINE
# ─────────────────────────────────────────────────────────────
def delete_medicine(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk)
    name = medicine.name
    medicine.delete()
    messages.success(request, f"{name} deleted.")
    return redirect('dashboard')


# ─────────────────────────────────────────────────────────────
# TAKE EMERGENCY DOSE
# ─────────────────────────────────────────────────────────────
def take_emergency(request, pk):
    medicine = get_object_or_404(Medicine, pk=pk)

    if medicine.medicine_type != 'emergency':
        messages.error(request, "This is not an emergency medicine.")
        return redirect('dashboard')

    if medicine.remaining_tablets <= 0:
        messages.error(request, f"{medicine.name} is already finished.")
        return redirect('dashboard')

    cause = request.POST.get('cause', 'Emergency dose taken.')

    dose = medicine.tablets_per_dose
    medicine.remaining_tablets = max(0, medicine.remaining_tablets - dose)
    medicine.save()

    MedicineHistory.objects.create(
        medicine=medicine,
        medicine_name=medicine.name,
        entry_type='dose',
        tablets=dose,
        price=0,
        note=f"🚨 Emergency dose — Reason: {cause}"
    )

    messages.success(request, f"{medicine.name}: dose taken.")
    return redirect('dashboard')


# ─────────────────────────────────────────────────────────────
# HISTORY VIEW
# ─────────────────────────────────────────────────────────────
def history_view(request):
    filter_month = request.GET.get('month', '')
    filter_date = request.GET.get('date', '')
    sort = request.GET.get('sort', '-created_at')

    allowed_sorts = ['-created_at', 'created_at', 'medicine_name']
    if sort not in allowed_sorts:
        sort = '-created_at'

    # Only purchases, refills, and emergency doses (not auto doses)
    med_history = MedicineHistory.objects.filter(
        entry_type__in=['purchase', 'refill', 'dose']
    ).exclude(
        entry_type='dose',
        note__icontains='auto dose'
    ).order_by(sort)

    if filter_date:
        try:
            d = datetime.date.fromisoformat(filter_date)
            med_history = med_history.filter(created_at__date=d)
        except ValueError:
            pass
    elif filter_month:
        try:
            year, month = filter_month.split('-')
            med_history = med_history.filter(created_at__year=year, created_at__month=month)
        except ValueError:
            pass

    total_purchases = med_history.filter(entry_type='purchase').count()
    total_refills = med_history.filter(entry_type='refill').count()
    total_emergency = med_history.filter(entry_type='dose').count()

    med_spend = med_history.exclude(entry_type='dose').aggregate(total=Sum('price'))['total'] or 0
    total_spent = float(med_spend)

    context = {
        'med_history': med_history,
        'total_purchases': total_purchases,
        'total_refills': total_refills,
        'total_emergency': total_emergency,
        'med_spend': med_spend,
        'total_spent': total_spent,
        'filter_month': filter_month,
        'filter_date': filter_date,
        'sort': sort,
    }

    return render(request, 'medicines/history.html', context)


# ─────────────────────────────────────────────────────────────
# EXPENSES VIEW
# ─────────────────────────────────────────────────────────────
def expenses_view(request):
    filter_month = request.GET.get('month', '')
    filter_date = request.GET.get('date', '')
    sort = request.GET.get('sort', '-expense_date')

    allowed_sorts = ['expense_date', '-expense_date', 'amount', '-amount', 'title']
    if sort not in allowed_sorts:
        sort = '-expense_date'

    expenses = Expense.objects.all().order_by(sort)

    if filter_date:
        try:
            d = datetime.date.fromisoformat(filter_date)
            expenses = expenses.filter(expense_date=d)
        except ValueError:
            pass
    elif filter_month:
        try:
            year, month = filter_month.split('-')
            expenses = expenses.filter(expense_date__year=year, expense_date__month=month)
        except ValueError:
            pass

    total = expenses.aggregate(total=Sum('amount'))['total'] or 0

    by_category = {}
    for exp in expenses:
        cat = exp.get_category_display()
        by_category[cat] = by_category.get(cat, 0) + float(exp.amount)

    context = {
        'expenses': expenses,
        'total': total,
        'by_category': by_category,
        'filter_month': filter_month,
        'filter_date': filter_date,
        'sort': sort,
        'categories': Expense.CATEGORY_CHOICES,
    }

    return render(request, 'medicines/expenses.html', context)

# ─────────────────────────────────────────────────────────────
# CLEAR HISTORY
# ─────────────────────────────────────────────────────────────
def clear_history(request):
    if request.method == "POST":
        MedicineHistory.objects.all().delete()
        messages.success(request, "History cleared successfully.")
    return redirect('history')


# ─────────────────────────────────────────────────────────────
# ADD EXPENSE
# ─────────────────────────────────────────────────────────────
def add_expense(request):
    if request.method == "POST":
        try:
            title = request.POST.get("title", "").strip()
            amount = float(request.POST.get("amount", 0))
            quantity = int(request.POST.get("quantity", 1) or 1)
            category = request.POST.get("category")
            expense_date = request.POST.get("expense_date")

            if not title or amount <= 0:
                messages.error(request, "Invalid expense data.")
                return redirect("expenses")

            Expense.objects.create(
                title=title,
                amount=amount * quantity,  # total price saved
                quantity=quantity,
                category=category,
                expense_date=expense_date
            )

            messages.success(request, f"Expense added: {quantity} x ₹{amount} = ₹{amount*quantity:.2f}")
            return redirect("expenses")

        except ValueError:
            messages.error(request, "Invalid input.")
            return redirect("expenses")

    return redirect("expenses")


# ─────────────────────────────────────────────────────────────
# DELETE EXPENSE
# ─────────────────────────────────────────────────────────────
def delete_expense(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    expense.delete()
    messages.success(request, "Expense deleted successfully.")
    return redirect('expenses')


# ─────────────────────────────────────────────────────────────
# AI CHATBOT
# ─────────────────────────────────────────────────────────────



def ai_chatbot(request):
    user_message = request.GET.get('message', '').strip()
    if not user_message:
        return JsonResponse({"response": "Please ask a question."})

    medicines = Medicine.objects.all()
    med_list = "\n".join(
        [f"- {m.name} | Type: {m.medicine_type} | Price: ₹{m.price} | Remaining: {m.remaining_tablets} tablets"
         for m in medicines]
    ) or "No medicines in database."

    system_prompt = f"""You are a knowledgeable medical information assistant with expertise in all medicines and diseases.

Medicines in user's database:
{med_list}

Your responsibilities:
- Answer questions about ANY medicine (not just ones in the database)
- When asked about a disease or symptom, suggest suitable medicines and treatments
- When asked about a specific medicine, explain its uses, side effects, and dosage
- If asked about stock (e.g. "do I have paracetamol?"), check the database above
- Provide helpful, accurate medical information for all queries

Always end with: ⚠️ Always consult a doctor before taking any medication.
Keep responses concise and friendly."""
    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        reply = response.choices[0].message.content

    except Exception as e:
        reply = f"Sorry, I couldn't process your request. Error: {str(e)}"

    return JsonResponse({"response": reply})

def download_expenses_pdf(request):
    filter_month = request.GET.get('month', '')
    filter_date = request.GET.get('date', '')

    expenses = Expense.objects.all().order_by("-expense_date")

    if filter_date:
        try:
            d = datetime.date.fromisoformat(filter_date)
            expenses = expenses.filter(expense_date=d)
        except ValueError:
            pass
    elif filter_month:
        try:
            year, month = filter_month.split('-')
            expenses = expenses.filter(expense_date__year=year, expense_date__month=month)
        except ValueError:
            pass

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="expenses.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Expense Report", styles['Title']))
    story.append(Spacer(1, 12))

    if filter_date:
        story.append(Paragraph(f"Date: {filter_date}", styles['Normal']))
    elif filter_month:
        story.append(Paragraph(f"Month: {filter_month}", styles['Normal']))
    else:
        story.append(Paragraph("All Expenses", styles['Normal']))
    story.append(Spacer(1, 12))

    data = [['#', 'Title', 'Category', 'Qty', 'Unit Price', 'Total', 'Date']]
    grand_total = 0

    for i, exp in enumerate(expenses, 1):
        qty = exp.quantity if hasattr(exp, 'quantity') else 1
        unit_price = float(exp.amount) / qty if qty > 1 else float(exp.amount)
        row_total = float(exp.amount)
        grand_total += row_total
        data.append([
            str(i),
            exp.title,
            exp.get_category_display(),
            str(qty),
            f"Rs {unit_price:.2f}",
            f"Rs {row_total:.2f}",
            str(exp.expense_date),
        ])

    data.append(['', '', '', '', '', f"TOTAL: Rs {grand_total:.2f}", ''])

    table = Table(data, colWidths=[25, 120, 90, 30, 70, 90, 75])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4f46e5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f3f4f6')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fef3c7')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))

    story.append(table)
    doc.build(story)
    return response


def download_history_pdf(request):
    filter_month = request.GET.get('month', '')
    filter_date = request.GET.get('date', '')

    med_history = MedicineHistory.objects.filter(
        entry_type__in=['purchase', 'refill', 'dose']
    ).exclude(
        entry_type='dose',
        note__icontains='auto dose'
    ).order_by('-created_at')

    if filter_date:
        try:
            d = datetime.date.fromisoformat(filter_date)
            med_history = med_history.filter(created_at__date=d)
        except ValueError:
            pass
    elif filter_month:
        try:
            year, month = filter_month.split('-')
            med_history = med_history.filter(created_at__year=year, created_at__month=month)
        except ValueError:
            pass

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="medicine_history.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Medicine History Report", styles['Title']))
    story.append(Spacer(1, 12))

    if filter_date:
        story.append(Paragraph(f"Date: {filter_date}", styles['Normal']))
    elif filter_month:
        story.append(Paragraph(f"Month: {filter_month}", styles['Normal']))
    else:
        story.append(Paragraph("All History", styles['Normal']))
    story.append(Spacer(1, 12))

    data = [['#', 'Medicine', 'Type', 'Tablets', 'Price', 'Note', 'Date']]

    for i, entry in enumerate(med_history, 1):
        type_label = 'Purchase' if entry.entry_type == 'purchase' else \
                     'Refill' if entry.entry_type == 'refill' else 'Emergency Dose'
        data.append([
            str(i),
            entry.medicine_name,
            type_label,
            str(entry.tablets),
            f"Rs {float(entry.price):.2f}" if entry.price > 0 else '—',
            entry.note[:40] + '...' if len(entry.note) > 40 else entry.note,
            entry.created_at.strftime('%d %b %Y'),
        ])

    table = Table(data, colWidths=[25, 110, 80, 45, 60, 130, 70])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4f46e5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))

    story.append(table)
    doc.build(story)
    return response