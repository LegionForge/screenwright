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


def test_validate_reports_duplicate_flow_names_clearly(tmp_path):
    # ScreenwrightConfig's duplicate-flow-name check is a model-level
    # validator (no single field to point at), so its Pydantic error has
    # an empty `loc` — this guards that _format_validation_errors renders
    # that case as "(root): ..." rather than a raw traceback or a blank
    # line.
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
        [[flows]]
        name = "homepage"

          [[flows.steps]]
          action = "navigate"
          url = "/"

        [[flows]]
        name = "homepage"

          [[flows.steps]]
          action = "navigate"
          url = "/about"
        """
    )

    result = runner.invoke(app, ["validate", str(toml_path)])

    assert result.exit_code == 1
    assert "Config validation failed" in result.output
    assert "(root)" in result.output
    assert "Duplicate flow name" in result.output


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


def test_flows_lists_each_flow_with_step_and_capture_counts(tmp_path):
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

          [[flows.steps]]
          action = "capture"
          name = "homepage-hero"

        [[flows]]
        name = "login"

          [[flows.steps]]
          action = "navigate"
          url = "/login"
        """
    )

    result = runner.invoke(app, ["flows", str(toml_path)])

    assert result.exit_code == 0
    assert "homepage" in result.output
    assert "3 steps, 2 capture(s)" in result.output
    assert "login" in result.output
    assert "1 steps, 0 capture(s)" in result.output


def test_flows_reports_no_flows_defined(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text("")

    result = runner.invoke(app, ["flows", str(toml_path)])

    assert result.exit_code == 0
    assert "No flows defined" in result.output


def test_flows_reports_toml_syntax_errors_instead_of_a_raw_traceback(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text("not [valid toml at all")

    result = runner.invoke(app, ["flows", str(toml_path)])

    assert result.exit_code == 1
    assert "TOML syntax error" in result.output
    assert isinstance(result.exception, SystemExit)


def test_version_flag_prints_installed_version_and_exits(tmp_path):
    from screenwright import __version__

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output
