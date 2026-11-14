from dataclasses import dataclass, field
from typing import Callable, Optional

from .models import Job, JobEvidence


@dataclass(frozen=True)
class QuestionStep:
    key: str                      # name shown in messages
    field_name: str               # the Job field this question fills
    required: bool = True
    applies_to: Callable[['Job'], bool] = lambda job: True

    def is_complete(self, job):
        return getattr(job, self.field_name) not in (None, '')

    def missing_message(self):
        return f'پاسخ به «{self.key}» ثبت نشده است.'


@dataclass(frozen=True)
class PhotoStep:
    key: str
    category: str                 # a JobEvidence.Category value
    minimum: int = 1
    maximum: Optional[int] = None
    kind: str = JobEvidence.Kind.PHOTO
    applies_to: Callable[['Job'], bool] = lambda job: True

    def count(self, job):
        return job.evidence.filter(kind=self.kind, category=self.category).count()

    def is_complete(self, job):
        n = self.count(job)
        if n < self.minimum:
            return False
        if self.maximum is not None and n > self.maximum:
            return False
        return True

    def missing_message(self):
        if self.maximum:
            return f'{self.key}: حداقل {self.minimum} و حداکثر {self.maximum} مورد لازم است.'
        return f'{self.key}: حداقل {self.minimum} مورد لازم است.'


@dataclass(frozen=True)
class MaterialsStep:
    key: str
    allowed_codes: tuple                     # material codes the technician may pick from
    minimum_items: int = 1
    maximum_items: Optional[int] = None      # None = no upper limit
    purpose: str = 'used'                    # 'used' or 'needed' (see JobMaterialUsage.Purpose)
    applies_to: Callable[['Job'], bool] = lambda job: True

    def usages(self, job):
        return job.material_usages.filter(
            purpose=self.purpose, material__code__in=self.allowed_codes,
        )

    def is_complete(self, job):
        n = self.usages(job).count()
        if n < self.minimum_items:
            return False
        if self.maximum_items is not None and n > self.maximum_items:
            return False
        return True

    def missing_message(self):
        return f'{self.key}: حداقل {self.minimum_items} ماده باید انتخاب شود.'


@dataclass(frozen=True)
class DescriptionStep:
    key: str = 'توضیحات'
    applies_to: Callable[['Job'], bool] = lambda job: True

    def is_complete(self, job):
        return hasattr(job, 'report') and bool(job.report.description.strip())

    def missing_message(self):
        return 'توضیحات کار ثبت نشده است.'






FTTH_FEASIBLE = Job.FtthOutcome.FEASIBLE
FTTH_UNFEASIBLE = Job.FtthOutcome.UNFEASIBLE
FTTH_NEEDS_MATERIALS = Job.FtthOutcome.NEEDS_MATERIALS

WORKFLOWS = {
    Job.Workflow.FTTH_INQUIRY: [
        QuestionStep(key='نتیجه امکان‌سنجی', field_name='ftth_outcome'),

        PhotoStep(
            key='عکس', category=JobEvidence.Category.GENERAL, minimum=1,
            applies_to=lambda job: job.ftth_outcome == FTTH_UNFEASIBLE,
        ),
        PhotoStep(
            key='ویدیو', category=JobEvidence.Category.VIDEO,
            minimum=1, kind=JobEvidence.Kind.VIDEO,
            applies_to=lambda job: job.ftth_outcome == FTTH_UNFEASIBLE,
        ),
        PhotoStep(
            key='عکس', category=JobEvidence.Category.GENERAL, minimum=2,
            applies_to=lambda job: job.ftth_outcome == FTTH_NEEDS_MATERIALS,
        ),
        MaterialsStep(
            key='متریال مورد نیاز',
            allowed_codes=('M003', 'M004', 'M007', 'M008'),
            purpose='needed',
            applies_to=lambda job: job.ftth_outcome == FTTH_NEEDS_MATERIALS,
        ),

        DescriptionStep(),
    ],

    Job.Workflow.DROP_CABLE: [
        MaterialsStep(
            key='متریال',
            allowed_codes=('M001', 'M002', 'M004', 'M009', 'M005'),
        ),
        PhotoStep(key='عکس دراپ', category=JobEvidence.Category.CABLE_LOCATION, minimum=3),
        PhotoStep(key='عکس FAT', category=JobEvidence.Category.FAT, minimum=1),
        PhotoStep(key='عکس ورودی', category=JobEvidence.Category.ENTRANCE, minimum=1),
        PhotoStep(key='عکس رسید', category=JobEvidence.Category.RECEIPT, minimum=1),

        QuestionStep(key='استفاده از توکار', field_name='tokar_used'),
        PhotoStep(
            key='عکس توکار', category=JobEvidence.Category.TOKAR, minimum=1,
            applies_to=lambda job: job.tokar_used is True,
        ),

        DescriptionStep(),
    ],

    Job.Workflow.FUSION: [
        QuestionStep(key='نیاز به اسپلیتر', field_name='fat_needs_splitter'),

        MaterialsStep(
            key='متریال اسپلیتر', allowed_codes=('M010', 'M012', 'M013'), minimum_items=2,
            applies_to=lambda job: job.fat_needs_splitter is True,
        ),
        PhotoStep(
            key='قبل اجرای اسپلیتر', category=JobEvidence.Category.SPLITTER_BEFORE, minimum=1,
            applies_to=lambda job: job.fat_needs_splitter is True,
        ),
        PhotoStep(
            key='بعد اجرای اسپلیتر', category=JobEvidence.Category.SPLITTER_AFTER, minimum=1,
            applies_to=lambda job: job.fat_needs_splitter is True,
        ),
        PhotoStep(
            key='آرایش کاست', category=JobEvidence.Category.CASSETTE, minimum=1,
            applies_to=lambda job: job.fat_needs_splitter is True,
        ),
        PhotoStep(
            key='عکس FAT', category=JobEvidence.Category.FAT, minimum=1,
            applies_to=lambda job: job.fat_needs_splitter is True,
        ),

        MaterialsStep(
            key='متریال',
            allowed_codes=('M014', 'M015', 'M016', 'M011', 'M017'),
            applies_to=lambda job: job.fat_needs_splitter is False,
        ),
        PhotoStep(
            key='عکس', category=JobEvidence.Category.GENERAL, minimum=5,
            applies_to=lambda job: job.fat_needs_splitter is False,
        ),

        DescriptionStep(),
    ],

    Job.Workflow.SERVICE_DELIVERY: [
        QuestionStep(key='سرعت آپلود', field_name='upload_mbps'),
        QuestionStep(key='سرعت دانلود', field_name='download_mbps'),
        MaterialsStep(
            key='مودم', allowed_codes=('M018', 'M019'), minimum_items=1, maximum_items=1,
        ),
        PhotoStep(key='عکس صورت جلسه', category=JobEvidence.Category.MOM, minimum=1),
        PhotoStep(key='عکس تست پان', category=JobEvidence.Category.PON_TEST, minimum=1),
        PhotoStep(key='عکس تست سرعت', category=JobEvidence.Category.SPEED_TEST, minimum=1),

        DescriptionStep(),
    ],

    Job.Workflow.MALFUNCTION: [
        PhotoStep(key='عکس', category=JobEvidence.Category.GENERAL, minimum=1, maximum=7),

        QuestionStep(key='استفاده از متریال', field_name='materials_used'),
        MaterialsStep(
            key='متریال',
            allowed_codes=tuple(f'M{i:03d}' for i in range(1, 20)),
            applies_to=lambda job: job.materials_used is True,
        ),

        DescriptionStep(),
    ],
}


def steps_for(job):
    """All steps defined for this job's workflow, in order."""
    return WORKFLOWS[job.workflow]


def applicable_steps(job):
    """Only the steps that apply to this job, given its current answers."""
    return [step for step in steps_for(job) if step.applies_to(job)]


def missing_requirements(job):
    return [step.missing_message() for step in applicable_steps(job) if not step.is_complete(job)]


def next_step(job):
    for step in applicable_steps(job):
        if not step.is_complete(job):
            return step
    return None