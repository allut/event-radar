"""Every LLM_TASK_* constant must fit `llm_calls.task`, or the cache insert fails."""
from app.constants import llm as llm_constants
from app.models.llm import LlmCall


def test_every_task_name_fits_llm_calls_task_column() -> None:
    limit = LlmCall.__table__.c.task.type.length
    tasks = {
        name: value
        for name, value in vars(llm_constants).items()
        if name.startswith("LLM_TASK_") and isinstance(value, str)
    }
    assert tasks
    too_long = {name: value for name, value in tasks.items() if len(value) > limit}
    assert not too_long, f"longer than llm_calls.task ({limit}): {too_long}"
