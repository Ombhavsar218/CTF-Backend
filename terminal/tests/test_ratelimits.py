from django.test import SimpleTestCase

from terminal.ratelimits import TokenBucket


class TokenBucketTests(SimpleTestCase):
    def test_burst_is_bounded(self):
        bucket = TokenBucket(rate=1, burst=2)
        self.assertTrue(bucket.consume(2))
        self.assertFalse(bucket.consume(1))

    def test_zero_amount_is_free(self):
        bucket = TokenBucket(rate=1, burst=1)
        self.assertTrue(bucket.consume(0))
        self.assertTrue(bucket.consume(1))
