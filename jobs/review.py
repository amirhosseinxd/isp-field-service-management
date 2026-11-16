from . import workflows


def _answer_text(job, field_name):
    value = getattr(job, field_name)
    if value in (None, ''):
        return 'پاسخ داده نشده'
    if field_name == 'ftth_outcome':
        return job.get_ftth_outcome_display()
    if isinstance(value, bool):
        return 'بله' if value else 'خیر'
    if field_name in ('upload_mbps', 'download_mbps'):
        return f'{value} Mbps'
    return str(value)


def review_sections(job):
    """One section per applicable workflow step, with the data the office should see."""
    sections = []
    for step in workflows.applicable_steps(job):
        complete = step.is_complete(job)
        section = {
            'title': step.key,
            'complete': complete,
            'message': '' if complete else step.missing_message(),
        }

        if isinstance(step, workflows.QuestionStep):
            section.update(kind='answer', value=_answer_text(job, step.field_name))

        elif isinstance(step, workflows.PhotoStep):
            section.update(
                kind=step.kind,
                items=job.evidence.filter(
                    kind=step.kind, category=step.category,
                ).select_related('uploaded_by'),
            )

        elif isinstance(step, workflows.MaterialsStep):
            section.update(
                kind='materials',
                items=step.usages(job).select_related('material'),
            )

        elif isinstance(step, workflows.DescriptionStep):
            report = getattr(job, 'report', None)
            section.update(kind='text', value=report.description if report else '')

        sections.append(section)
    return sections