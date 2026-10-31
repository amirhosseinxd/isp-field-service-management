from django.contrib import admin
from .models import Job, WorkReport,JobEvidence




class JobEvidenceInline(admin.TabularInline):
    model = JobEvidence
    extra = 0



class WorkReportInline(admin.StackedInline):
    model = WorkReport
    extra = 0







@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('id', 'job_type', 'workflow', 'assigned_operator', 'status', 'created_at', 'submitted_at')
    list_filter = ('job_type', 'workflow', 'status', 'assigned_operator')
    inlines = [JobEvidenceInline, WorkReportInline]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for inst in instances:
            if isinstance(inst, JobEvidence) and not inst.pk:
                inst.uploaded_by = request.user
            if isinstance(inst, WorkReport) and not inst.pk:
                inst.submitted_by = request.user
            inst.save()
        formset.save_m2m()