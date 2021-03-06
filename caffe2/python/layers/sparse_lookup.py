## @package sparse_lookup
# Module caffe2.python.layers.sparse_lookup
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from caffe2.python import core, schema
from caffe2.python.layers.layers import (
    IdList,
    IdScoreList,
    LayerParameter,
    LayerPsParam,
    ModelLayer,
)
import functools
import math
import numpy as np
import operator


class SparseLookup(ModelLayer):
    _supported_reducers = ['PositionWeighted', 'LogMeanExp', 'LogSumExp', 'Max',
                           'Mean', 'Sum', 'Sqrt']

    def __init__(self, model, input_record, inner_shape, reducer,
                 weight_init=None, weight_optim=None,
                 name='sparse_lookup', **kwargs):
        super(SparseLookup, self).__init__(model, name, input_record, **kwargs)

        if isinstance(inner_shape, int):
            inner_shape = [inner_shape]
        assert isinstance(inner_shape, list) or isinstance(inner_shape, tuple),\
            "Unexpected type for inner_shape, expected list or tuple, got {0}".\
            format(type(inner_shape))

        # TODO Add some asserts about input type
        assert reducer in self._supported_reducers, "Unsupported reducer: {}".\
            format(reducer)
        self.reducer = reducer

        assert input_record.items.metadata is not None,\
            "Features without metadata are not supported"
        input_dim = input_record.items.metadata.categorical_limit
        assert input_dim is not None, "Unbounded features are not supported"

        self.output_schema = schema.Scalar(
            (np.float32, inner_shape),
            model.net.NextScopedBlob(name + '_output'),
        )

        if self.request_only:
            schema.attach_metadata_to_scalars(
                self.output_schema,
                schema.Metadata(
                    categorical_limit=None,
                    expected_value=None,
                    feature_specs=schema.FeatureSpec(
                        feature_is_request_only=True
                    )
                )
            )
        scale = math.sqrt(1.0 / input_dim)
        self.shape = [input_dim] + inner_shape
        self.weight_init = weight_init if weight_init else (
            'UniformFill', {'min': -scale, 'max': scale})

        self.w = model.net.NextScopedBlob(name + "_w")
        if self.input_record.lengths.metadata:
            avg_length = self.input_record.lengths.metadata.expected_value
        else:
            avg_length = None
        self.params.append(
            LayerParameter(
                parameter=self.w,
                initializer=core.CreateOperator(self.weight_init[0],
                                                [],
                                                self.w,
                                                shape=self.shape,
                                                **self.weight_init[1]
                                                ),
                optimizer=weight_optim,
                ps_param=LayerPsParam(
                    sparse_key=self.input_record.items(),
                    average_length=avg_length
                )
            ))

        if reducer == 'PositionWeighted':
            self.pos_w = model.net.NextScopedBlob(name + "_pos_w")
            self.params.append(
                LayerParameter(
                    parameter=self.pos_w,
                    initializer=core.CreateOperator('ConstantFill',
                                                    [],
                                                    self.pos_w,
                                                    shape=[input_dim, ],
                                                    value=1.0
                                                    ),
                    optimizer=weight_optim
                ))

    def get_memory_usage(self):
        return functools.reduce(operator.mul, self.shape) * 4

    def get_fp16_compatible_parameters(self):
        return [self.w]

    def add_ops(self, net):
        if schema.equal_schemas(self.input_record, IdList):
            if self.reducer == 'Sum':
                net.SparseLengthsSum(
                    [
                        self.w,
                        self.input_record.items(),
                        self.input_record.lengths()
                    ],
                    self.output_schema.field_blobs(),
                    engine='fp16'
                )
            elif self.reducer == 'PositionWeighted':
                inc_seq = net.LengthsRangeFill(
                    [self.input_record.lengths()],
                    self.input_record.lengths() + '_seq'
                )
                gather_pos_w = net.Gather(
                    [self.pos_w, inc_seq], self.pos_w + '_gather')

                net.SparseLengthsWeightedSum(
                    [
                        self.w,
                        gather_pos_w,
                        self.input_record.items(),
                        self.input_record.lengths()
                    ],
                    self.output_schema.field_blobs(),
                    grad_on_weights=1,
                    engine='fp16'
                )
            elif self.reducer == 'Sqrt':
                sqrt_weight = net.LengthsToWeights(
                    [self.input_record.lengths()],
                    [self.input_record.lengths() + '_sqrt'],
                    power=0.5
                )
                net.SparseLengthsWeightedSum(
                    [
                        self.w,
                        sqrt_weight,
                        self.input_record.items(),
                        self.input_record.lengths()
                    ],
                    self.output_schema.field_blobs(),
                    engine='fp16'
                )
            else:
                table_rows = net.Gather([self.w, self.input_record.items()])
                segment_ids = net.LengthsToSegmentIds(
                    self.input_record.lengths(),
                    self.input_record.lengths() + '_sid')
                net.__getattr__('SortedSegmentRange' + self.reducer)(
                    [table_rows, segment_ids],
                    self.output_schema.field_blobs(),
                    engine='fp16'
                )
        elif schema.equal_schemas(self.input_record, IdScoreList):
            if self.reducer == 'Sum':
                net.SparseLengthsWeightedSum(
                    [
                        self.w,
                        self.input_record.values(),
                        self.input_record.keys(),
                        self.input_record.lengths()
                    ],
                    self.output_schema.field_blobs(),
                    engine='fp16'
                )
            else:
                raise "Only Sum is supported for IdScoreList input." +\
                    "Trying to create with {}".format(self.reducer)
        else:
            raise "Unsupported input type {0}".format(self.input_record)
