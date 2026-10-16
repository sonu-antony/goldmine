"""The dbt project as Dagster assets. Every dbt model is an asset, every dbt test an asset check."""

import shutil
import sys
from pathlib import Path

from dagster import AssetExecutionContext, AssetKey
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

DBT_PROJECT_DIR = Path(__file__).resolve().parents[1] / "goldmine_dbt"

dbt_project = DbtProject(project_dir=DBT_PROJECT_DIR)
dbt_project.prepare_if_dev()

# The dbt installed next to this Python (the virtual environment), found even when it is not activated.
DBT_EXECUTABLE = shutil.which("dbt") or str(Path(sys.executable).parent / "dbt")

dbt_resource = DbtCliResource(project_dir=dbt_project, profiles_dir=str(DBT_PROJECT_DIR), dbt_executable=DBT_EXECUTABLE)


class GoldmineTranslator(DagsterDbtTranslator):
    def get_asset_key(self, dbt_resource_props):
        # A dbt source is the raw table the loader writes, so it must have the same key as the loader asset.
        if dbt_resource_props["resource_type"] == "source":
            return AssetKey(["raw", dbt_resource_props["name"]])
        return super().get_asset_key(dbt_resource_props)

    def get_group_name(self, dbt_resource_props):
        # staging, intermediate, gold, snapshots: the folder under models/
        fqn = dbt_resource_props.get("fqn", [])
        return fqn[1] if len(fqn) > 2 else "dbt"


@dbt_assets(manifest=dbt_project.manifest_path, dagster_dbt_translator=GoldmineTranslator())
def goldmine_dbt_models(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()
