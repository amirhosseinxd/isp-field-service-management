from dataclasses import dataclass
from typing import Callable, Optional

from .models import Job, JobEvidence


@dataclass(frozen=True)
class QuestionStep:
    key: str
    field_name: str
    required: bool = True
    applies_to: Callable[['Job'], bool] = lambda job: True

    def is_complete(self, job):
        return getattr(job, self.field_name) not in (None, '')

    def missing_message(self):
        return f'پاسخ به «{self.key}» ثبت نشده است.'


@dataclass(frozen=True)
class PhotoStep:
    key: str
    category: str
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
    allowed_codes: tuple
    minimum_items: int = 1
    maximum_items: Optional[int] = None
    required_codes: tuple = ()     # these must always be picked
    exactly_one_of: tuple = ()     # exactly one of these must be picked
    purpose: str = 'used'          # 'used' or 'needed'
    applies_to: Callable[['Job'], bool] = lambda job: True

    def usages(self, job):
        return job.material_usages.filter(
            purpose=self.purpose, material__code__in=self.allowed_codes,
        )

    def problem(self, codes):
        """The first rule the chosen codes break, as a Farsi message, or None if all is fine."""
        chosen = set(codes)
        if any(code not in chosen for code in self.required_codes):
            return f'{self.key}: یکی از موارد اجباری انتخاب نشده است.'
        if self.exactly_one_of and len(chosen & set(self.exactly_one_of)) != 1:
            return f'{self.key}: دقیقاً یکی از موارد را انتخاب کنید.'
        if len(chosen) < self.minimum_items:
            return f'{self.key}: حداقل {self.minimum_items} ماده باید انتخاب شود.'
        if self.maximum_items is not None and len(chosen) > self.maximum_items:
            return f'{self.key}: حداکثر {self.maximum_items} ماده مجاز است.'
        return None

    def current_problem(self, job):
        """The Farsi reason this step is incomplete, or None if it's complete."""
        codes = list(self.usages(job).values_list('material__code', flat=True))
        return self.problem(codes)

    def is_complete(self, job):
        return self.current_problem(job) is None

    def missing_message(self):
        return f'{self.key}: هنوز کامل نشده است.'


@dataclass(frozen=True)
class DescriptionStep:
    key: str = 'توضیحات'
    applies_to: Callable[['Job'], bool] = lambda job: True

    def is_complete(self, job):
        return hasattr(job, 'report') and bool(job.report.description.strip())

    def missing_message(self):
        return 'توضیحات کار ثبت نشده است.'


FTTH_NEEDS_MATERIALS = Job.FtthOutcome.NEEDS_MATERIALS
FTTH_UNFEASIBLE = Job.FtthOutcome.UNFEASIBLE

ALL_MALFUNCTION_CODES = tuple(f'M{i:03d}' for i in range(1, 20))

WORKFLOWS = {
    Job.Workflow.FTTH_INQUIRY: [
        QuestionStep(key='نتیجه امکان‌سنجی', field_name='ftth_outcome'),

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
        PhotoStep(
            key='ویدیو', category=JobEvidence.Category.VIDEO,
            minimum=1, kind=JobEvidence.Kind.VIDEO,
            applies_to=lambda job: job.ftth_outcome == FTTH_UNFEASIBLE,
        ),

        DescriptionStep(),
    ],

    Job.Workflow.DROP_CABLE: [
        MaterialsStep(
            key='متریال', allowed_codes=('M001', 'M002', 'M004', 'M009', 'M005'),
        ),
        PhotoStep(key='عکس دراپ', category=JobEvidence.Category.CABLE_LOCATION, minimum=3),
        PhotoStep(key='عکس FAT', category=JobEvidence.Category.FAT, minimum=1),
        PhotoStep(key='عکس ورودی', category=JobEvidence.Category.ENTRANCE, minimum=1),
        PhotoStep(key='عکس رسید', category=JobEvidence.Category.RECEIPT, minimum=1),

        QuestionStep(key='استفاده از توکار', field_name='tokar_used'),
        MaterialsStep(
            key='متراژ توکار', allowed_codes=('M006',), minimum_items=1, maximum_items=1,
            applies_to=lambda job: job.tokar_used is True,
        ),
        PhotoStep(
            key='عکس توکار', category=JobEvidence.Category.TOKAR, minimum=1,
            applies_to=lambda job: job.tokar_used is True,
        ),

        DescriptionStep(),
    ],

    Job.Workflow.FUSION: [
        QuestionStep(key='نیاز به اسپلیتر', field_name='fat_needs_splitter'),

        MaterialsStep(
            key='متریال اسپلیتر',
            allowed_codes=('M010', 'M012', 'M013'),
            required_codes=('M010',),
            exactly_one_of=('M012', 'M013'),
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
            allowed_codes=ALL_MALFUNCTION_CODES,
            applies_to=lambda job: job.materials_used is True,
        ),

        DescriptionStep(),
    ],
}


def steps_for(job):
    """All steps defined for this job's workflow, in order."""
    return WORKFLOWS[job.workflow]

def message_for(step, job):
    """The Farsi message explaining why this step is incomplete."""
    if isinstance(step, MaterialsStep):
        return step.current_problem(job) or step.missing_message()
    return step.missing_message()


def applicable_steps(job):
    """Only the steps that apply to this job, given its current answers."""
    return [step for step in steps_for(job) if step.applies_to(job)]


def missing_requirements(job):
    """Everything still missing, including the description. Used by Job.submit()."""
    return [message_for(step, job) for step in applicable_steps(job) if not step.is_complete(job)]


def missing_before_description(job):
    """Everything missing except the description, which the user is writing right now."""
    return [
        message_for(step, job)
        for step in applicable_steps(job)
        if not isinstance(step, DescriptionStep) and not step.is_complete(job)
    ]

def next_step(job):
    for step in applicable_steps(job):
        if not step.is_complete(job):
            return step
    return None