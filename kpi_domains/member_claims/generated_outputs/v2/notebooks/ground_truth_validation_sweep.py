# Databricks notebook source
# COMMAND ----------
%pip install pyyaml

dbutils.library.restartPython()

# COMMAND ----------
import dbldatagen

# COMMAND ----------
import sys
sys.path.insert(0, "/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/framework/templates")
from gate_checks import run_cross_validation, write_ground_truth_validation

OUTPUT_FOLDER = "/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v2"
quality_gates = {
    "min_widgets_per_canvas_page": 2,
    "min_filters_per_dashboard": 3,
    "min_datasets_per_dashboard": 1,
    "min_canvas_pages_per_dashboard": 1,
    "min_genie_instruction_chars": 200,
    "min_genie_tables": 1,
    "min_genie_sample_questions": 5,
    "min_genie_example_sqls": 5,
    "min_genie_description_chars": 50,
}
report = run_cross_validation(OUTPUT_FOLDER, quality_gates=quality_gates)
write_ground_truth_validation(f"{OUTPUT_FOLDER}/ground_truth_validation.yaml", report, source="cross_validation_sweep")
print(report)

