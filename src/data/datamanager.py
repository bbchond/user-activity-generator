from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, List, Literal, TypeVar, Optional, Set

import pandas
import pyarrow
from pandas import DataFrame
from pyarrow.parquet import ParquetFile, ParquetSchema

from ..config import Config
from .dataset import Dataset, Activity
from .filetype import FileType


class DataManager:
    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset

    def generate_features(self, raw: DataFrame) -> None:
        generators = self.dataset.generators()
        if generators:
            for gen_key, gen_function in generators.items():
                raw[gen_key] = gen_function(raw)

    def convert_dataset(self) -> DataFrame:
        print(f"Converting raw to interim: {self.path}")
        self.delete_interim()
        raw_dataframe = self.dataset.read()
        self.generate_features(raw_dataframe)
        self.path.parent.mkdir(0o755, parents=True, exist_ok=True)
        raw_dataframe.to_parquet(self.path)
        return raw_dataframe

    def read(self, columns: List[str] = None, clean: bool = False) -> DataFrame:
        if clean or self.is_interim_dirty():
            self.convert_dataset()
        return pandas.read_parquet(
            self.path, columns=columns if columns else list(self.dataset.COLUMNS.keys())
        )

    def stream(
        self,
        activities: Set[Activity],
        window: int,
        stride: Optional[int] = None,
        subjects: Optional[Set[int]] = None,
        clean: bool = False,
    ) -> DataFrame:
        stride = stride if stride else window
        data = self.read(clean=clean)
        activity_keys = [self.dataset.ACTIVITIES[activity] for activity in activities]
        filtered = data.loc[data[self.dataset.ACTIVITY_COLUMN].isin(activity_keys)]
        if subjects:
            filtered = filtered.loc[
                filtered[self.dataset.SUBJECT_COLUMN].isin(subjects)
            ]
        for _, data in filtered.groupby(
            [self.dataset.TRIAL_COLUMN, self.dataset.SUBJECT_COLUMN]
        ):
            for i in range((len(filtered) - window) // stride):
                yield filtered.iloc[i * stride : i * stride + window]

    def read_schema(self) -> ParquetSchema:
        return ParquetFile(self.path).schema

    def is_interim_dirty(self) -> bool:
        return not self.path.exists() or self.any_missing_features()

    def any_missing_features(self) -> bool:
        interim_cols = self.read_schema().names
        raw_cols = self.dataset.COLUMNS.keys()
        return any([col not in interim_cols for col in raw_cols])

    def delete_interim(self) -> None:
        if self.path.exists():
            self.path.unlink()

    @property
    def path(self) -> Path:
        return Path(Config.INTERIM_ROOT / self.dataset.hash[: Config.HASH_LENGTH])
