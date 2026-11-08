"""Apply the frozen supervisor failure/cleanup contracts to the new sampler."""
from unittest.mock import patch
import zkfdo_runtime_v1_test as previous
import zkfdo_runtime_v2 as runtime


class RuntimeV2Tests(previous.RuntimeTests):
    def setUp(self):
        self.runtime_patch = patch.object(previous, 'runtime', runtime)
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        super().setUp()
