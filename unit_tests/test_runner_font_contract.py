import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('font_builder', ROOT/'scripts/prepare_runner_dockerfile.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
SOURCE = '''FROM pinned-base
RUN apt-get install -y --no-install-recommends novnc x11vnc
COPY --from=yanjia_web --chown=pwuser:pwuser utils /opt/yanjia-web/utils
USER pwuser
'''


def test_fixed_font_and_browser_gate_are_required():
    result = builder.prepare(SOURCE)
    assert builder.FONT_PACKAGE in result
    assert 'fc-cache -f' in result
    assert 'apt-get purge -y fonts-wqy-zenhei' in result
    assert result.index('USER pwuser') < result.index('RUN python /opt/yanjia-web/utils/browser_font_health.py')
    assert '\n+' not in result


@pytest.mark.parametrize('source', [SOURCE.replace('novnc x11vnc', 'changed'), SOURCE.replace('USER pwuser','USER root'), SOURCE+SOURCE])
def test_changed_upstream_contract_fails(source):
    with pytest.raises(ValueError): builder.prepare(source)


def test_reapplying_contract_fails():
    with pytest.raises(ValueError): builder.prepare(builder.prepare(SOURCE))


def test_release_workflow_uses_generated_dockerfile():
    workflow = (ROOT/'.github/workflows/testops-release.yml').read_text('utf-8')
    assert 'python scripts/prepare_runner_dockerfile.py' in workflow
    assert 'file: .testops-platform/infra/docker/yanjia-web-font-validated.Dockerfile' in workflow
