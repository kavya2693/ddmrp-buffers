import pytest

from ddmrp_buffers import data


@pytest.fixture(scope="session")
def small_range() -> data.Dataset:
    # 60 SKUs keeps the suite fast while still covering imports, blends and every lifecycle.
    return data.generate(seed=11, n_skus=60)
