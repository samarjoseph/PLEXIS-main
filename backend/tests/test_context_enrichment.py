"""
Test Suite: Generic Analytical Context Enrichment, Exact Record Provenance & Unit Grounding
Verifies:
  1. Complete record contextual attributes (Airline, Flight Number, Origin, Destination, Date, Scheduled Time).
  2. Grounded units (known vs unknown vs dimensionless / explicit None).
  3. Tied extrema (accurate tie count and honest representation).
  4. Missing contextual fields (honest fallback without fabricating data).
  5. Cross-domain datasets (Flights, Telco, E-Commerce, Healthcare).
  6. Mismatched provenance and system column exclusion.
  7. Exact source-row provenance (source row vs dataframe index vs result rank).
  8. Verifier rejections for ungrounded units and hallucinated context attributes.
  9. Deterministic narrative composition.
"""
import pytest
import pandas as pd
from analytics.context_enrichment import (
    extract_relevant_context,
    format_context_summary,
    enrich_extremum_narrative,
)
from analytics.unit_resolver import resolve_unit, UnitResolution
from verifier.result_verifier import result_verifier, VerifierResult
from executor.pandas_executor import ExecutorResult
from planner.schema import AnalyticalPlan


class TestContextEnrichment:

    def test_complete_flight_record_context_extraction(self):
        """Flight record extracts all 6 core attributes including composite Scheduled Departure Time."""
        row = {
            "_row_number": 146821,
            "source_row_number": 146821,
            "dataframe_index": 146820,
            "result_rank": 1,
            "Flight_Date": "2025-09-01",
            "Airline": "SpiceJet",
            "Flight_Number": "SP9257",
            "Origin_Airport": "COK",
            "Destination_Airport": "JRH",
            "Scheduled_Departure_Hour": 21,
            "Scheduled_Departure_Minute": 1,
            "Departure_Delay": 119,
        }
        ctx = extract_relevant_context(row, target_col="Departure_Delay", max_fields=8)

        # Assert target metric and system columns excluded
        assert "Departure_Delay" not in ctx
        assert "_row_number" not in ctx
        assert "source_row_number" not in ctx
        assert "dataframe_index" not in ctx
        assert "result_rank" not in ctx

        # Assert all 6 core contextual attributes are present
        assert ctx["Airline"] == "SpiceJet"
        assert ctx["Flight_Number"] == "SP9257"
        assert ctx["Origin_Airport"] == "COK"
        assert ctx["Destination_Airport"] == "JRH"
        assert ctx["Flight_Date"] == "2025-09-01"
        assert ctx["Scheduled Departure Time"] == "21:01"

        # Raw separate hour/minute columns are cleanly composed and suppressed
        assert "Scheduled_Departure_Hour" not in ctx
        assert "Scheduled_Departure_Minute" not in ctx

        # Assert narrative composition includes complete context and source row
        narrative = enrich_extremum_narrative(
            op="max",
            col="Departure_Delay",
            val=119,
            matching_rows=[row],
            dataset_name="Flight Operations",
            details={
                "matching_count": 1,
                "unit_status": "unknown",
                "unit_label": "Unit not specified in dataset metadata",
            },
        )
        assert "In **Flight Operations**, the highest **Departure_Delay** is **119**" in narrative
        assert "[Unit not specified in dataset metadata]" in narrative
        assert "Airline: SpiceJet" in narrative
        assert "Flight Number: SP9257" in narrative
        assert "Origin Airport: COK" in narrative
        assert "Destination Airport: JRH" in narrative
        assert "Flight Date: 2025-09-01" in narrative
        assert "Scheduled Departure Time: 21:01" in narrative
        assert "Source row: 146821" in narrative

    def test_extremum_with_known_and_unknown_units(self):
        """Verified unit appears when grounded; never inferred or guessed when unknown."""
        row = {"Product": "Ergonomic Keyboard", "Category": "Hardware", "Price": 149.99}

        # Case A: Known unit from metadata
        narrative_with_unit = enrich_extremum_narrative(
            op="max",
            col="Price",
            val=149.99,
            matching_rows=[row],
            dataset_name="Catalog",
            unit="USD",
        )
        assert "is **149.99 USD**" in narrative_with_unit

        # Case B: Unknown unit (None) with explicit unknown label
        narrative_no_unit = enrich_extremum_narrative(
            op="max",
            col="Departure_Delay",
            val=119,
            matching_rows=[row],
            dataset_name="Flights",
            unit=None,
            details={
                "unit_status": "unknown",
                "unit_label": "Unit not specified in dataset metadata",
            },
        )
        assert "is **119** [Unit not specified in dataset metadata]" in narrative_no_unit
        assert "minutes" not in narrative_no_unit

    def test_unit_resolver_trusted_sources_and_precedence(self):
        """Unit resolver queries trusted sources in order and never guesses."""
        # 1. Undocumented column -> unknown
        res1 = resolve_unit(column="Departure_Delay", operation="max")
        assert res1.status == "unknown"
        assert res1.unit is None
        assert res1.label == "Unit not specified in dataset metadata"

        # 2. Dimensionless operations -> not_applicable
        res2 = resolve_unit(column="total_rows", operation="count")
        assert res2.status == "not_applicable"
        assert res2.unit is None

        # 3. Explicit dataset metadata
        meta = {"columns": {"Price": {"unit": "USD"}}}
        res3 = resolve_unit(column="Price", operation="max", dataset_metadata=meta)
        assert res3.status == "known"
        assert res3.unit == "USD"
        assert res3.provenance == "column_metadata"

        # 4. Data dictionary
        data_dict = {"temperature": {"unit": "°C"}}
        res4 = resolve_unit(column="temperature", operation="mean", data_dictionary=data_dict)
        assert res4.status == "known"
        assert res4.unit == "°C"
        assert res4.provenance == "data_dictionary"

        # 5. User definition
        user_defs = {"distance": "km"}
        res5 = resolve_unit(column="distance", operation="sum", user_definitions=user_defs)
        assert res5.status == "known"
        assert res5.unit == "km"
        assert res5.provenance == "user_definition"

    def test_tied_extrema_honestly_represented(self):
        """When multiple records tie for maximum or minimum, tie count and multiple records are surfaced."""
        row1 = {"Airline": "SpiceJet", "Origin": "DEL", "Departure_Delay": 119, "source_row_number": 42}
        row2 = {"Airline": "Air India", "Origin": "BOM", "Departure_Delay": 119, "source_row_number": 105}
        row3 = {"Airline": "IndiGo", "Origin": "BLR", "Departure_Delay": 119, "source_row_number": 880}

        narrative = enrich_extremum_narrative(
            op="max",
            col="Departure_Delay",
            val=119,
            matching_rows=[row1, row2, row3],
            dataset_name="Flights",
            details={"matching_count": 3},
        )
        assert "tied across **3 records**" in narrative
        assert "Row 42: Airline: SpiceJet, Origin: DEL" in narrative
        assert "Row 105: Airline: Air India, Origin: BOM" in narrative

    def test_missing_contextual_fields(self):
        """When a dataset has no other non-metric columns, result displays cleanly without error or invented context."""
        row = {"_row_number": 1, "Reading": 98.6}
        ctx = extract_relevant_context(row, target_col="Reading", max_fields=4)
        assert ctx == {}

        narrative = enrich_extremum_narrative(
            op="max",
            col="Reading",
            val=98.6,
            matching_rows=[row],
            dataset_name="Sensor Data",
            details={"matching_count": 1},
        )
        assert "In **Sensor Data**, the highest **Reading** is **98.6**" in narrative
        assert "Source row: 1" in narrative

    def test_cross_domain_telco_schema(self):
        """Telecom churn dataset correctly extracts customer ID, contract, and service context."""
        telco_row = {
            "customerID": "7590-VHVEG",
            "Contract": "Two year",
            "InternetService": "Fiber optic",
            "PaymentMethod": "Electronic check",
            "MonthlyCharges": 118.75,
            "TotalCharges": 8684.8,
        }
        ctx = extract_relevant_context(telco_row, target_col="TotalCharges", max_fields=4)
        assert "Contract" in ctx
        assert ctx["Contract"] == "Two year"
        assert "InternetService" in ctx
        assert ctx["customerID"] == "7590-VHVEG"
        assert "TotalCharges" not in ctx

    def test_cross_domain_healthcare_schema(self):
        """Clinical/hospital schema extracts patient entity and categorical diagnosis."""
        patient_row = {
            "Patient_ID": "PT-4401",
            "Hospital": "St. Jude",
            "Diagnosis": "Arrhythmia",
            "Admission_Type": "Emergency",
            "Stay_Days": 45,
        }
        ctx = extract_relevant_context(patient_row, target_col="Stay_Days", max_fields=4)
        assert ctx["Patient_ID"] == "PT-4401"
        assert ctx["Hospital"] == "St. Jude"
        assert ctx["Diagnosis"] == "Arrhythmia"
        assert "Stay_Days" not in ctx

    def test_mismatched_provenance_and_null_filtering(self):
        """Null, NaN, empty strings, and internal metadata are safely skipped."""
        dirty_row = {
            "_row_number": 10,
            "level_0": 0,
            "Airline": "Alliance Air",
            "Origin": None,
            "Destination": "   ",
            "Gate": float("nan"),
            "Delay": 85,
        }
        ctx = extract_relevant_context(dirty_row, target_col="Delay", max_fields=4)
        assert "Origin" not in ctx
        assert "Destination" not in ctx
        assert "Gate" not in ctx
        assert ctx == {"Airline": "Alliance Air"}

    def test_minimum_extremum_labeling(self):
        """Minimum operation correctly labeled as lowest."""
        row = {"Airline": "Fly91", "Route": "GOI-BOM", "Departure_Delay": -12, "source_row_number": 5}
        narrative = enrich_extremum_narrative(
            op="min",
            col="Departure_Delay",
            val=-12,
            matching_rows=[row],
            dataset_name="Flights",
            details={"matching_count": 1},
        )
        assert "lowest **Departure_Delay** is **-12**" in narrative
        assert "Airline: Fly91" in narrative


class TestResultVerifierGroundingAndProvenance:

    def test_result_verifier_ungrounded_unit_rejection(self):
        """Verifier rejects fabricated/ungrounded units with UNGROUNDED_UNIT."""
        df = pd.DataFrame({
            "Departure_Delay": [10, 25, 119, 45],
            "Airline": ["IndiGo", "SpiceJet", "Air India", "Akasa"],
        })
        plan = AnalyticalPlan(intent="max_delay", operation="max", target_column="Departure_Delay", plan=[])
        exec_res = ExecutorResult(
            value=119,
            operation="max",
            column="Departure_Delay",
            details={"unit": "minutes"},  # Fabricated unit not in metadata!
            matching_rows=[{"Airline": "Air India", "Departure_Delay": 119, "dataframe_index": 2}],
        )

        # No metadata supplied -> Departure_Delay has unknown unit
        vr = result_verifier.verify(exec_res, plan, df, dataset_metadata={})
        assert vr.verified is False
        assert vr.error_code == "UNGROUNDED_UNIT"
        assert "Claimed unit 'minutes' is not documented" in vr.error_message

    def test_result_verifier_context_attribute_mismatch_rejection(self):
        """Verifier rejects hallucinated contextual attributes that do not match the source row."""
        df = pd.DataFrame({
            "Departure_Delay": [10, 25, 119, 45],
            "Airline": ["IndiGo", "SpiceJet", "Air India", "Akasa"],
        })
        plan = AnalyticalPlan(intent="max_delay", operation="max", target_column="Departure_Delay", plan=[])
        # Claimed row says Airline is 'Emirates', but row index 2 in df is 'Air India'
        exec_res = ExecutorResult(
            value=119,
            operation="max",
            column="Departure_Delay",
            matching_rows=[{"Airline": "Emirates", "Departure_Delay": 119, "dataframe_index": 2}],
        )

        vr = result_verifier.verify(exec_res, plan, df)
        assert vr.verified is False
        assert vr.error_code == "RECORD_CONTEXT_MISMATCH"
        assert "Emirates" in vr.error_message
        assert "Air India" in vr.error_message

    def test_result_verifier_success_with_authentic_extremum_context(self):
        """Verifier succeeds when value, row index, and context match the DataFrame exactly."""
        df = pd.DataFrame({
            "Departure_Delay": [10, 25, 119, 45],
            "Airline": ["IndiGo", "SpiceJet", "Air India", "Akasa"],
        })
        plan = AnalyticalPlan(intent="max_delay", operation="max", target_column="Departure_Delay", plan=[])
        exec_res = ExecutorResult(
            value=119,
            operation="max",
            column="Departure_Delay",
            details={"unit": None, "unit_status": "unknown"},
            matching_rows=[{"Airline": "Air India", "Departure_Delay": 119, "dataframe_index": 2, "source_row_number": 3}],
        )

        vr = result_verifier.verify(exec_res, plan, df)
        assert vr.verified is True
        assert vr.expected == 119
        assert vr.actual == 119
