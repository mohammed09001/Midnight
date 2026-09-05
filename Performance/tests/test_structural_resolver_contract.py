import unittest

from midnight_performance.structural_resolver_contract import (
    IdentityStrategy,
    ResolverCapability,
    ResolverDescriptor,
)


def _descriptor(**overrides) -> ResolverDescriptor:
    fields = dict(
        language="python", tool="stdlib-ast", tool_version="1",
        capabilities=frozenset({ResolverCapability.STRUCTURE, ResolverCapability.SYMBOLS}),
        max_bytes=1_000_000, identity_strategy=IdentityStrategy.REPOSITORY_FILE_QUALIFIED_SYMBOL,
        supported=True, gap=None, uncertainty="derived structural projection",
    )
    fields.update(overrides)
    return ResolverDescriptor(**fields)


class StructuralResolverContractTests(unittest.TestCase):
    def test_a_valid_supported_descriptor_constructs(self):
        descriptor = _descriptor()
        self.assertTrue(descriptor.supported)
        self.assertIsNone(descriptor.gap)

    def test_a_valid_unsupported_descriptor_constructs(self):
        descriptor = _descriptor(
            supported=False, identity_strategy=IdentityStrategy.NONE,
            gap="unsupported language; no structural symbol resolution", capabilities=frozenset(),
        )
        self.assertFalse(descriptor.supported)

    def test_supported_resolver_must_declare_a_real_identity_strategy(self):
        with self.assertRaises(ValueError):
            _descriptor(identity_strategy=IdentityStrategy.NONE)

    def test_unsupported_resolver_must_disclose_a_gap(self):
        with self.assertRaises(ValueError):
            _descriptor(supported=False, identity_strategy=IdentityStrategy.NONE, gap=None)

    def test_uncertainty_disclosure_is_required(self):
        with self.assertRaises(ValueError):
            _descriptor(uncertainty="")
        with self.assertRaises(ValueError):
            _descriptor(uncertainty="   ")

    def test_language_tool_and_tool_version_are_required(self):
        with self.assertRaises(ValueError):
            _descriptor(language="")
        with self.assertRaises(ValueError):
            _descriptor(tool="")
        with self.assertRaises(ValueError):
            _descriptor(tool_version="")

    def test_max_bytes_must_be_positive(self):
        with self.assertRaises(ValueError):
            _descriptor(max_bytes=0)
        with self.assertRaises(ValueError):
            _descriptor(max_bytes=-1)


if __name__ == "__main__":
    unittest.main()
