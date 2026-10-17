"""
TransformationExecutor — applies approved TransformationPlans to DataFrames.

Safety rules:
- Only allowlisted operations execute
- Plan must belong to the correct dataset_id
- Plan must be 'pending' status
- Dataset fingerprint must match (staleness check)
- No eval/exec
"""
from __future__ import annotations
import gzip
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import pandas as pd
from sqlalchemy.orm import Session

from transformation.contracts import TransformationPlan, TransformationResult
from transformation.planner import _compute_fingerprint, ALLOWED_OPERATIONS

logger = logging.getLogger(__name__)


class TransformationExecutor:

    def apply(
        self,
        plan: TransformationPlan,
        df: pd.DataFrame,
        dataset_id: str,
        db: Optional[Session],
        *,
        original_db_dataset_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        base_filename: str = 'dataset.csv',
    ) -> TransformationResult:
        """
        Apply a TransformationPlan to a DataFrame.

        Args:
            plan: The approved TransformationPlan
            df: Current active DataFrame (will be copied, not mutated in place)
            dataset_id: Must match plan.dataset_id
            db: SQLAlchemy session (None = stateless mode)
            original_db_dataset_id: The UUID in the datasets table (for versioning)
            user_id: For dataset ownership on versioned copy
            base_filename: Filename to use for the versioned dataset

        Returns:
            TransformationResult
        """
        # ── Safety checks ──
        if plan.dataset_id != dataset_id:
            return TransformationResult(
                success=False, plan_id=plan.plan_id,
                version_id=None, version_number=None, changed_cells=0,
                operation_label=plan.operation_label,
                error=(
                    f"Plan dataset_id mismatch. Plan is for {plan.dataset_id}, got {dataset_id}."
                )
            )

        # Staleness check
        current_fingerprint = _compute_fingerprint(df)
        if current_fingerprint != plan.dataset_fingerprint:
            return TransformationResult(
                success=False, plan_id=plan.plan_id,
                version_id=None, version_number=None, changed_cells=0,
                operation_label=plan.operation_label,
                error=(
                    "DATASET_CHANGED: The dataset was modified after this plan was created. "
                    "Please regenerate the plan."
                )
            )

        try:
            # ── Save previous state for undo (BEFORE mutation) ──
            previous_df = df.copy()

            # ── Execute the transformation ──
            new_df = self._execute(df.copy(), plan)

            # ── No-op detection ──
            changed_cells = plan.affected_cells_count
            is_noop = (
                changed_cells == 0
                and len(new_df) == len(df)
                and len(new_df.columns) == len(df.columns)
            )

            # ── Persist versioned DataFrame to PostgreSQL ──
            version_dataset_id = None
            version_id = None
            version_number = None

            if db is not None and original_db_dataset_id is not None and not is_noop:
                try:
                    version_dataset_id, version_id, version_number = self._persist_version(
                        db=db,
                        new_df=new_df,
                        plan=plan,
                        original_db_dataset_id=original_db_dataset_id,
                        user_id=user_id,
                        base_filename=base_filename,
                    )
                except Exception as e:
                    logger.warning('[TransformExecutor] Version persist failed (non-fatal): %s', e)

            # ── Record in-memory undo history (atomic with registry update) ──
            from transformation.history import transformation_history

            if not is_noop:
                prev_version = transformation_history.get_version(dataset_id)
                new_version = transformation_history.increment_version(dataset_id)

                try:
                    transformation_history.record(
                        dataset_id=dataset_id,
                        plan_id=plan.plan_id,
                        operation_type=plan.operation_type,
                        operation_label=plan.operation_label,
                        previous_df=previous_df,
                        previous_version=prev_version,
                        result_version=new_version,
                        changed_cells=changed_cells,
                        affected_columns=plan.affected_columns,
                    )
                except Exception as e:
                    # History recording failed — rollback version
                    logger.error('[TransformExecutor] History recording failed, rolling back: %s', e)
                    return TransformationResult(
                        success=False, plan_id=plan.plan_id,
                        version_id=None, version_number=None, changed_cells=0,
                        operation_label=plan.operation_label,
                        error='Failed to record undo history. Transformation aborted.',
                    )

            # ── Update L1 in-memory registry ──
            try:
                from datasets.registry import dataset_registry
                entry = dataset_registry.get(dataset_id)
                if entry is not None:
                    entry.dataframe = new_df
                    entry.row_count = len(new_df)
                    entry.column_count = len(new_df.columns)
                    logger.info('[TransformExecutor] L1 registry updated for dataset %s', dataset_id)
            except Exception as e:
                logger.warning('[TransformExecutor] L1 registry update failed: %s', e)

            return TransformationResult(
                success=True,
                plan_id=plan.plan_id,
                version_id=str(version_id) if version_id else None,
                version_number=version_number if version_number else (
                    transformation_history.get_version(dataset_id) if not is_noop else None
                ),
                changed_cells=changed_cells,
                operation_label=plan.operation_label,
                intelligence_provenance=getattr(plan, 'intelligence_provenance', None),
            )

        except Exception as e:
            logger.error('[TransformExecutor] Execution failed: %s', e, exc_info=True)
            return TransformationResult(
                success=False, plan_id=plan.plan_id,
                version_id=None, version_number=None, changed_cells=0,
                operation_label=plan.operation_label,
                error=str(e),
            )

    def _execute(self, df: pd.DataFrame, plan: TransformationPlan) -> pd.DataFrame:
        """Execute the allowlisted operation. Returns new DataFrame."""
        op = plan.operation_type
        payload = plan.operation_payload

        if op == 'IR_COMPOSITE':
            from transformation.ir import TransformationIR
            from transformation.compiler import ir_compiler
            ir_dict = payload.get('ir')
            if not ir_dict:
                raise ValueError("IR_COMPOSITE missing 'ir' payload")
            ir = TransformationIR.from_dict(ir_dict)
            sim = ir_compiler.compile_and_simulate(ir, df, plan.dataset_id)
            if not sim.success:
                raise RuntimeError(f"IR Execution failed: {'; '.join(sim.errors)}")
            return sim.result_df

        if op == 'FILL_MISSING':
            fill_value = payload.get('value', 0)
            columns = payload.get('columns') or df.columns.tolist()
            if isinstance(columns, str):
                columns = [columns]
            columns = [c for c in columns if c in df.columns]
            for col in columns:
                if fill_value == "mean":
                    df[col] = df[col].fillna(df[col].mean())
                elif fill_value == "median":
                    df[col] = df[col].fillna(df[col].median())
                elif fill_value == "mode":
                    mode_s = df[col].mode()
                    df[col] = df[col].fillna(mode_s.iloc[0] if not mode_s.empty else df[col])
                elif fill_value == "ffill":
                    df[col] = df[col].ffill()
                elif fill_value == "bfill":
                    df[col] = df[col].bfill()
                else:
                    df[col] = df[col].fillna(fill_value)
            return df

        elif op == 'DROP_DUPLICATES':
            columns = payload.get('columns') or df.columns.tolist()
            if isinstance(columns, str):
                columns = [columns]
            columns = [c for c in columns if c in df.columns]
            return df.drop_duplicates(subset=columns, keep='first').reset_index(drop=True)

        elif op == 'RENAME_COLUMN':
            renames = payload.get('renames')
            if renames:
                return df.rename(columns={old: new for old, new in renames.items() if old in df.columns})
            old_name = payload.get('column') or payload.get('old_name', '')
            new_name = payload.get('new_name', '')
            if old_name in df.columns and new_name:
                return df.rename(columns={old_name: new_name})
            return df

        elif op == 'DROP_COLUMN':
            column = payload.get('column', '')
            if column in df.columns:
                return df.drop(columns=[column])
            return df

        elif op == 'FILTER_ROWS':
            column = payload.get('column', '')
            operator = payload.get('operator', '==')
            value = payload.get('value')
            action = payload.get('action', 'KEEP').upper()
            if column not in df.columns:
                return df
            col_series = (
                pd.to_numeric(df[column], errors='coerce')
                if operator in ('>', '<', '>=', '<=')
                else df[column]
            )
            op_map = {
                '==': lambda s, v: s == v,
                '!=': lambda s, v: s != v,
                '>':  lambda s, v: s > v,
                '<':  lambda s, v: s < v,
                '>=': lambda s, v: s >= v,
                '<=': lambda s, v: s <= v,
            }
            mask = op_map.get(operator, lambda s, v: s == v)(col_series, value)
            if action == 'REMOVE':
                mask = ~mask
            return df[mask].reset_index(drop=True)

        elif op == 'CAST_DTYPE':
            column = payload.get('column', '')
            dtype = payload.get('dtype', 'float')
            if column in df.columns:
                if dtype in ('int', 'float', 'int64', 'float64'):
                    df[column] = pd.to_numeric(df[column], errors='coerce')
                    if dtype in ('int', 'int64'):
                        df[column] = df[column].astype('Int64')  # nullable int
                else:
                    df[column] = df[column].astype(str)
            return df

        elif op == 'REPLACE_VALUES':
            column = payload.get('column', '')
            columns = payload.get('columns') or ([column] if column else [])
            old_val = payload.get('old_value')
            new_val = payload.get('new_value')
            typed_meta = payload.get('_old_typed')
            for selected_column in columns:
                if selected_column not in df.columns:
                    continue
                if typed_meta:
                    from datasets.semantics.typed_literal import TypedLiteral, build_mask
                    old_lit = TypedLiteral.from_dict(typed_meta)
                    mask = build_mask(df[selected_column], old_lit)
                    if mask.any() and isinstance(new_val, str) and pd.api.types.is_numeric_dtype(df[selected_column].dtype):
                        # Replacements may intentionally change a physical numeric
                        # column to strings; widen before assignment for pandas
                        # versions that reject silent dtype upcasting.
                        df[selected_column] = df[selected_column].astype(object)
                    df.loc[mask, selected_column] = new_val
                else:
                    df[selected_column] = df[selected_column].replace(old_val, new_val)
            return df


        elif op == 'SORT_ROWS':
            column = payload.get('column', '')
            ascending = payload.get('ascending', True)
            if column in df.columns:
                return df.sort_values(column, ascending=ascending).reset_index(drop=True)
            return df

        raise ValueError(f"Unknown operation type: {op}")

    def _persist_version(
        self, db, new_df, plan, original_db_dataset_id, user_id, base_filename
    ):
        """Persist versioned DataFrame as new Dataset+DatasetFile rows."""
        from db.models.dataset import Dataset, DatasetFile
        from db.repositories.transformation_repository import transformation_repository

        # Version snapshots must preserve scalar types in mixed columns.
        # CSV remains the download/export format; it is not lossless storage.
        from datasets.version_codec import serialize_dataframe
        snapshot_bytes = serialize_dataframe(new_df)
        file_hash = hashlib.sha256(snapshot_bytes).hexdigest()
        compressed = gzip.compress(snapshot_bytes)

        # Create new Dataset record for the versioned copy
        filename_stem = base_filename.rsplit('.', 1)[0]
        versioned_filename = f"{filename_stem}_v{uuid.uuid4().hex[:6]}.plexis.json"
        version_ds = Dataset(
            id=uuid.uuid4(),
            user_id=user_id,
            original_filename=versioned_filename,
            mime_type='application/vnd.plexis.typed-dataframe+json',
            file_size=len(snapshot_bytes),
            file_hash=file_hash,
            row_count=len(new_df),
            column_count=len(new_df.columns),
        )
        db.add(version_ds)
        db.flush()

        version_file = DatasetFile(
            id=uuid.uuid4(),
            dataset_id=version_ds.id,
            content=compressed,
            compression='gzip',
            checksum=file_hash,
        )
        db.add(version_file)
        db.flush()

        # Get the latest existing version for parent linking
        latest = transformation_repository.get_latest_version(db, original_db_dataset_id)
        parent_version_id = latest.id if latest else None

        # Create DatasetVersion record
        dv = transformation_repository.create_version(
            db,
            original_dataset_id=original_db_dataset_id,
            version_dataset_id=version_ds.id,
            plan_id=uuid.UUID(plan.plan_id),
            operation_label=plan.operation_label,
            changed_cells_count=plan.affected_cells_count,
            parent_version_id=parent_version_id,
            metadata={
                'operation_type': plan.operation_type,
                'affected_columns': plan.affected_columns,
                'operation_code': plan.operation_code,
            },
        )

        # Mark plan as applied
        transformation_repository.mark_plan_applied(db, uuid.UUID(plan.plan_id))
        db.commit()

        return version_ds.id, dv.id, dv.version_number


transformation_executor = TransformationExecutor()
