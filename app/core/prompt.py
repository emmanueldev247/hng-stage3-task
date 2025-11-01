from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.core.config import Config

_env = Environment(
    loader=FileSystemLoader(Config.PROMPT_DIR),
    autoescape=select_autoescape()
)
def render_system_prompt(deployment_label) -> str:
    tpl = _env.get_template(Config.PROMPT_FILE)
    deployment_reference = f" integrated on {deployment_label}" if deployment_label else ""
    return tpl.render(DEPLOYMENT_REFERENCE=deployment_reference)
