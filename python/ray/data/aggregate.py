import math
from typing import Callable, Optional, List, TYPE_CHECKING, Union

from ray.util.annotations import PublicAPI
from ray.data.block import (
    T,
    U,
    Block,
    BlockAccessor,
    KeyType,
    AggType,
    _validate_key_fn,
)
from ray.data._internal.null_aggregate import (
    _null_wrap_init,
    _null_wrap_merge,
    _null_wrap_accumulate_block,
    _null_wrap_finalize,
    _null_wrap_accumulate_row,
)

if TYPE_CHECKING:
    import pyarrow as pa


@PublicAPI
class AggregateFn:
    def __init__(
        self,
        init: Callable[[KeyType], AggType],
        merge: Callable[[AggType, AggType], AggType],
        accumulate_row: Callable[[AggType, T], AggType] = None,
        accumulate_block: Callable[[AggType, Block], AggType] = None,
        finalize: Callable[[AggType], U] = lambda a: a,
        name: Optional[str] = None,
    ):
        """Defines an aggregate function in the accumulator style.

        Aggregates a collection of inputs of type T into
        a single output value of type U.
        See https://www.sigops.org/s/conferences/sosp/2009/papers/yu-sosp09.pdf
        for more details about accumulator-based aggregation.

        Args:
            init: This is called once for each group to return the empty accumulator.
                For example, an empty accumulator for a sum would be 0.
            merge: This may be called multiple times, each time to merge
                two accumulators into one.
            accumulate_row: This is called once per row of the same group.
                This combines the accumulator and the row, returns the updated
                accumulator. Exactly one of accumulate_row and accumulate_block must
                be provided.
            accumulate_block: This is used to calculate the aggregation for a
                single block, and is vectorized alternative to accumulate_row. This will
                be given a base accumulator and the entire block, allowing for
                vectorized accumulation of the block. Exactly one of accumulate_row and
                accumulate_block must be provided.
            finalize: This is called once to compute the final aggregation
                result from the fully merged accumulator.
            name: The name of the aggregation. This will be used as the output
                column name in the case of Arrow dataset.
        """
        if (accumulate_row is None and accumulate_block is None) or (
            accumulate_row is not None and accumulate_block is not None
        ):
            raise ValueError(
                "Exactly one of accumulate_row or accumulate_block must be provided."
            )
        if accumulate_block is None:

            def accumulate_block(a: AggType, block: Block) -> AggType:
                block_acc = BlockAccessor.for_block(block)
                for r in block_acc.iter_rows(public_row_format=False):
                    a = accumulate_row(a, r)
                return a

        self.init = init
        self.merge = merge
        self.accumulate_block = accumulate_block
        self.finalize = finalize
        self.name = name

    def _validate(self, schema: Optional[Union[type, "pa.lib.Schema"]]) -> None:
        """Raise an error if this cannot be applied to the given schema."""
        pass


class _AggregateOnKeyBase(AggregateFn):
    def _set_key_fn(self, on: str):
        self._key_fn = on

    def _validate(self, schema: Optional[Union[type, "pa.lib.Schema"]]) -> None:
        _validate_key_fn(schema, self._key_fn)


@PublicAPI
class Count(AggregateFn):
    """Defines count aggregation."""

    def __init__(self):
        super().__init__(
            init=lambda k: 0,
            accumulate_block=(
                lambda a, block: a + BlockAccessor.for_block(block).num_rows()
            ),
            merge=lambda a1, a2: a1 + a2,
            name="count()",
        )


@PublicAPI
class Sum(_AggregateOnKeyBase):
    """Defines sum aggregation."""

    def __init__(
        self,
        on: Optional[str] = None,
        ignore_nulls: bool = True,
        alias_name: Optional[str] = None,
    ):
        self._set_key_fn(on)
        if alias_name:
            self._rs_name = alias_name
        else:
            self._rs_name = f"sum({str(on)})"

        null_merge = _null_wrap_merge(ignore_nulls, lambda a1, a2: a1 + a2)

        super().__init__(
            init=_null_wrap_init(lambda k: 0),
            merge=null_merge,
            accumulate_block=_null_wrap_accumulate_block(
                ignore_nulls,
                lambda block: BlockAccessor.for_block(block).sum(on, ignore_nulls),
                null_merge,
            ),
            finalize=_null_wrap_finalize(lambda a: a),
            name=(self._rs_name),
        )


@PublicAPI
class Min(_AggregateOnKeyBase):
    """Defines min aggregation."""

    def __init__(
        self,
        on: Optional[str] = None,
        ignore_nulls: bool = True,
        alias_name: Optional[str] = None,
    ):
        self._set_key_fn(on)
        if alias_name:
            self._rs_name = alias_name
        else:
            self._rs_name = f"min({str(on)})"

        null_merge = _null_wrap_merge(ignore_nulls, min)

        super().__init__(
            init=_null_wrap_init(lambda k: float("inf")),
            merge=null_merge,
            accumulate_block=_null_wrap_accumulate_block(
                ignore_nulls,
                lambda block: BlockAccessor.for_block(block).min(on, ignore_nulls),
                null_merge,
            ),
            finalize=_null_wrap_finalize(lambda a: a),
            name=(self._rs_name),
        )


@PublicAPI
class Max(_AggregateOnKeyBase):
    """Defines max aggregation."""

    def __init__(
        self,
        on: Optional[str] = None,
        ignore_nulls: bool = True,
        alias_name: Optional[str] = None,
    ):
        self._set_key_fn(on)
        if alias_name:
            self._rs_name = alias_name
        else:
            self._rs_name = f"max({str(on)})"

        null_merge = _null_wrap_merge(ignore_nulls, max)

        super().__init__(
            init=_null_wrap_init(lambda k: float("-inf")),
            merge=null_merge,
            accumulate_block=_null_wrap_accumulate_block(
                ignore_nulls,
                lambda block: BlockAccessor.for_block(block).max(on, ignore_nulls),
                null_merge,
            ),
            finalize=_null_wrap_finalize(lambda a: a),
            name=(self._rs_name),
        )


@PublicAPI
class Mean(_AggregateOnKeyBase):
    """Defines mean aggregation."""

    def __init__(
        self,
        on: Optional[str] = None,
        ignore_nulls: bool = True,
        alias_name: Optional[str] = None,
    ):
        self._set_key_fn(on)
        if alias_name:
            self._rs_name = alias_name
        else:
            self._rs_name = f"mean({str(on)})"

        null_merge = _null_wrap_merge(
            ignore_nulls, lambda a1, a2: [a1[0] + a2[0], a1[1] + a2[1]]
        )

        def vectorized_mean(block: Block) -> AggType:
            block_acc = BlockAccessor.for_block(block)
            count = block_acc.count(on)
            if count == 0 or count is None:
                # Empty or all null.
                return None
            sum_ = block_acc.sum(on, ignore_nulls)
            if sum_ is None:
                # ignore_nulls=False and at least one null.
                return None
            return [sum_, count]

        super().__init__(
            init=_null_wrap_init(lambda k: [0, 0]),
            merge=null_merge,
            accumulate_block=_null_wrap_accumulate_block(
                ignore_nulls,
                vectorized_mean,
                null_merge,
            ),
            finalize=_null_wrap_finalize(lambda a: a[0] / a[1]),
            name=(self._rs_name),
        )


@PublicAPI
class Std(_AggregateOnKeyBase):
    """Defines standard deviation aggregation.

    Uses Welford's online method for an accumulator-style computation of the
    standard deviation. This method was chosen due to its numerical
    stability, and it being computable in a single pass.
    This may give different (but more accurate) results than NumPy, Pandas,
    and sklearn, which use a less numerically stable two-pass algorithm.
    See
    https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Welford's_online_algorithm
    """

    def __init__(
        self,
        on: Optional[str] = None,
        ddof: int = 1,
        ignore_nulls: bool = True,
        alias_name: Optional[str] = None,
    ):
        self._set_key_fn(on)
        if alias_name:
            self._rs_name = alias_name
        else:
            self._rs_name = f"std({str(on)})"

        def merge(a: List[float], b: List[float]):
            # Merges two accumulations into one.
            # See
            # https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Parallel_algorithm
            M2_a, mean_a, count_a = a
            M2_b, mean_b, count_b = b
            delta = mean_b - mean_a
            count = count_a + count_b
            # NOTE: We use this mean calculation since it's more numerically
            # stable than mean_a + delta * count_b / count, which actually
            # deviates from Pandas in the ~15th decimal place and causes our
            # exact comparison tests to fail.
            mean = (mean_a * count_a + mean_b * count_b) / count
            # Update the sum of squared differences.
            M2 = M2_a + M2_b + (delta**2) * count_a * count_b / count
            return [M2, mean, count]

        null_merge = _null_wrap_merge(ignore_nulls, merge)

        def vectorized_std(block: Block) -> AggType:
            block_acc = BlockAccessor.for_block(block)
            count = block_acc.count(on)
            if count == 0 or count is None:
                # Empty or all null.
                return None
            sum_ = block_acc.sum(on, ignore_nulls)
            if sum_ is None:
                # ignore_nulls=False and at least one null.
                return None
            mean = sum_ / count
            M2 = block_acc.sum_of_squared_diffs_from_mean(on, ignore_nulls, mean)
            return [M2, mean, count]

        def finalize(a: List[float]):
            # Compute the final standard deviation from the accumulated
            # sum of squared differences from current mean and the count.
            M2, mean, count = a
            if count < 2:
                return 0.0
            return math.sqrt(M2 / (count - ddof))

        super().__init__(
            init=_null_wrap_init(lambda k: [0, 0, 0]),
            merge=null_merge,
            accumulate_block=_null_wrap_accumulate_block(
                ignore_nulls,
                vectorized_std,
                null_merge,
            ),
            finalize=_null_wrap_finalize(finalize),
            name=(self._rs_name),
        )


@PublicAPI
class AbsMax(_AggregateOnKeyBase):
    """Defines absolute max aggregation."""

    def __init__(
        self,
        on: Optional[str] = None,
        ignore_nulls: bool = True,
        alias_name: Optional[str] = None,
    ):
        self._set_key_fn(on)
        on_fn = _to_on_fn(on)
        if alias_name:
            self._rs_name = alias_name
        else:
            self._rs_name = f"abs_max({str(on)})"

        super().__init__(
            init=_null_wrap_init(lambda k: 0),
            merge=_null_wrap_merge(ignore_nulls, max),
            accumulate_row=_null_wrap_accumulate_row(
                ignore_nulls, on_fn, lambda a, r: max(a, abs(r))
            ),
            finalize=_null_wrap_finalize(lambda a: a),
            name=(self._rs_name),
        )


def _to_on_fn(on: Optional[str]):
    if on is None:
        return lambda r: r
    elif isinstance(on, str):
        return lambda r: r[on]
    else:
        return on


@PublicAPI
class Quantile(_AggregateOnKeyBase):
    """Defines Quantile aggregation."""

    def __init__(
        self,
        on: Optional[str] = None,
        q: float = 0.5,
        ignore_nulls: bool = True,
        alias_name: Optional[str] = None,
    ):
        self._set_key_fn(on)
        self._q = q
        if alias_name:
            self._rs_name = alias_name
        else:
            self._rs_name = f"quantile({str(on)})"

        def merge(a: List[int], b: List[int]):
            if isinstance(a, List) and isinstance(b, List):
                a.extend(b)
                return a
            if isinstance(a, List) and (not isinstance(b, List)):
                if b is not None and b != "":
                    a.append(b)
                return a
            if isinstance(b, List) and (not isinstance(a, List)):
                if a is not None and a != "":
                    b.append(a)
                return b

            ls = []
            if a is not None and a != "":
                ls.append(a)
            if b is not None and b != "":
                ls.append(b)
            return ls

        null_merge = _null_wrap_merge(ignore_nulls, merge)

        def block_row_ls(block: Block) -> AggType:
            block_acc = BlockAccessor.for_block(block)
            ls = []
            for row in block_acc.iter_rows(public_row_format=False):
                ls.append(row.get(on))
            return ls

        import math

        def percentile(input_values, key=lambda x: x):
            if not input_values:
                return None
            input_values = sorted(input_values)
            k = (len(input_values) - 1) * self._q
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return key(input_values[int(k)])
            d0 = key(input_values[int(f)]) * (c - k)
            d1 = key(input_values[int(c)]) * (k - f)
            return round(d0 + d1, 5)

        super().__init__(
            init=_null_wrap_init(lambda k: [0]),
            merge=null_merge,
            accumulate_block=_null_wrap_accumulate_block(
                ignore_nulls,
                block_row_ls,
                null_merge,
            ),
            finalize=_null_wrap_finalize(percentile),
            name=(self._rs_name),
        )
