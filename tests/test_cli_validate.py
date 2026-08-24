from __future__ import annotations

from typer.testing import CliRunner

from screenwright.cli import app

# Deliberately NOT marked @pytest.mark.integration — validate/error-path
# testing never launches a browser, so these run under
# `pytest -m 'not integration'` too (previously nothing in the capture
# engine's test files did).

runner = CliRunner()


def test_validate_accepts_a_well_formed_config(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
        [[flows]]
        name = "homepage"

          [[flows.steps]]
          action = "navigate"
          url = "/"

          [[flows.steps]]
          action = "capture"
          name = "homepage-full"
        """
    )

    result = runner.invoke(app, ["validate", str(toml_path)])

    assert result.exit_code == 0
    assert "Valid" in result.output
    assert "1 flow" in result.output
    assert "1 capture" in result.output


def test_validate_reports_toml_syntax_errors_clearly(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text("this is not [valid toml")

    result = runner.invoke(app, ["validate", str(toml_path)])

    assert result.exit_code == 1
    assert "TOML syntax error" in result.output


def test_validate_reports_schema_violations_clearly(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
        [[flows]]
        name = "bad"

          [[flows.steps]]
          action = "capture"
          name = "../escape"
        """
    )

    result = runner.invoke(app, ["validate", str(toml_path)])

    assert result.exit_code == 1
    assert "Config validation failed" in result.output
    assert "flows.0.steps.0" in result.output
    assert "path-traversal" in result.output


def test_validate_reports_missing_config_file(tmp_path):
    missing = tmp_path / "does-not-exist.toml"

    result = runner.invoke(app, ["validate", str(missing)])

    assert result.exit_code == 1
    assert "Config not found" in result.output


def test_run_reports_schema_violations_instead_of_a_raw_traceback(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
        [[flows]]
        name = "bad"

          [[flows.steps]]
          action = "capture"
          name = "../escape"
        """
    )

    result = runner.invoke(app, ["run", str(toml_path)])

    assert result.exit_code == 1
    assert "Config validation failed" in result.output
    # typer.Exit(1) raising SystemExit is the expected clean exit — what
    # this test actually guards against is an *unhandled* ValidationError
    # propagating instead, which CliRunner would surface as that exception
    # type here rather than SystemExit.
    assert isinstance(result.exception, SystemExit)


def test_flows_reports_toml_syntax_errors_instead_of_a_raw_traceback(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text("not [valid toml at all")

    result = runner.invoke(app, ["flows", str(toml_path)])

    assert result.exit_code == 1
    assert "TOML syntax error" in result.output
    assert isinstance(result.exception, SystemExit)
