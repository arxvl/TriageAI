from app.adapters.llm.ratelimit import RateLimiter


class FakeTime:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_disabled_limiter_never_waits():
    ft = FakeTime()
    rl = RateLimiter(0, clock=ft.clock, sleep=ft.sleep)
    assert all(rl.acquire() == 0.0 for _ in range(100)) and ft.slept == []


def test_allows_up_to_max_then_waits_for_the_window():
    ft = FakeTime()
    rl = RateLimiter(3, clock=ft.clock, sleep=ft.sleep)
    for _ in range(3):
        assert rl.acquire() == 0.0
    waited = rl.acquire()  # fourth call inside the same minute
    assert 59.9 <= waited <= 60.1 and len(ft.slept) == 1


def test_window_slides():
    ft = FakeTime()
    rl = RateLimiter(2, clock=ft.clock, sleep=ft.sleep)
    rl.acquire()
    ft.t = 30
    rl.acquire()
    ft.t = 61  # the first stamp has expired
    assert rl.acquire() == 0.0
