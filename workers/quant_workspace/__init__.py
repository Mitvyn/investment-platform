"""Desktop-local Quant workspace: dataset intake, analysis, and local storage.

This package is the worker-side boundary between an operator's local files and
the offline Quant core in ``investment_research_os.quant``. The dependency runs
one way: this package imports Quant contracts, and Quant imports nothing from
here, so the core stays provider-neutral and free of filesystem concerns.

The Quant bounded context shares exactly one field with Research and Portfolio:
the canonical ``security_id``. No Research evidence, thesis, committee result,
holding, position, sizing, or broker state enters this package, and nothing it
produces is evidence, a recommendation, or an instruction to trade. Results are
historical analysis of an operator-supplied dataset and nothing more.
"""
