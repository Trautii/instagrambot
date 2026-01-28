import logging
from random import randint, uniform
from time import sleep

from GramAddict.core.decorators import run_safely
from GramAddict.core.device_facade import Timeout
from GramAddict.core.plugin_loader import Plugin
from GramAddict.core.resources import ResourceID as resources
from GramAddict.core.utils import get_value, random_sleep
from GramAddict.core.views import Direction, TabBarView, UniversalActions, case_insensitive_re

logger = logging.getLogger(__name__)


class WatchReels(Plugin):
    """Watches reels in the Reels tab with optional auto-like"""

    def __init__(self):
        super().__init__()
        self.description = "Watch reels in the Reels tab with optional auto-like"
        self.arguments = [
            {
                "arg": "--watch-reels",
                "nargs": None,
                "help": "watch reels tab for the given amount (number or range). Disabled by default",
                "metavar": "5-10",
                "default": None,
                "operation": True,
            },
            {
                "arg": "--reels-like-percentage",
                "nargs": None,
                "help": "chance of liking a reel while watching, 0 by default",
                "metavar": "10-40",
                "default": "0",
            },
            {
                "arg": "--reels-watch-time",
                "nargs": None,
                "help": "seconds to stay on each reel before swiping (number or range)",
                "metavar": "5-8",
                "default": "5-8",
            },
            {
                "arg": "--reels-like-ads",
                "help": "allow likes on reels detected as ads (default: false)",
                "action": "store_true",
            },
        ]

    def run(self, device, configs, storage, sessions, profile_filter, plugin):
        self.device_id = configs.args.device
        self.sessions = sessions
        self.session_state = sessions[-1]
        self.args = configs.args
        self.current_mode = plugin
        self.ResourceID = resources(self.args.app_id)

        reels_count = get_value(self.args.watch_reels, "Reels to watch: {}", 0)
        if not reels_count:
            logger.info("No reels count provided, skipping reels watcher.")
            return
        like_percentage = get_value(self.args.reels_like_percentage, None, 0)
        dwell_seconds = get_value(self.args.reels_watch_time, None, 6, its_time=True)

        @run_safely(
            device=device,
            device_id=self.device_id,
            sessions=self.sessions,
            session_state=self.session_state,
            screen_record=self.args.screen_record,
            configs=configs,
        )
        def job():
            self._watch_reels(device, reels_count, like_percentage, dwell_seconds)

        job()

    def _watch_reels(self, device, reels_count: int, like_percentage: int, dwell: int):
        tab_bar = TabBarView(device)
        tab_bar.navigateToReels()
        random_sleep(inf=1, sup=2, modulable=False)

        watched = 0
        while watched < reels_count:
            if self.session_state.check_limit(
                limit_type=self.session_state.Limit.ALL, output=True
            )[0]:
                logger.info("Session limits reached, stopping reels.")
                break

            # Detect ad reel (but still watch); gate likes on ads by config
            is_ad, ad_reason = self._is_reel_ad(device)

            if is_ad and not self.args.reels_like_ads:
                logger.debug(f"Reel marked as ad ({ad_reason}); will not like.")

            if like_percentage and (self.args.reels_like_ads or not is_ad) and randint(
                1, 100
            ) <= like_percentage:
                like_btn = device.find(resourceIdMatches=self.ResourceID.LIKE_BUTTON)
                if not like_btn.exists():
                    like_btn = device.find(
                        descriptionMatches=case_insensitive_re("like")
                    )
                if like_btn.exists(Timeout.SHORT):
                    like_btn.click()
                    UniversalActions.detect_block(device)
                    self.session_state.totalLikes += 1
                    logger.info(
                        f"Liked reel #{watched + 1}{' (ad)' if is_ad else ''}."
                    )

            stay_time = max(1, dwell)
            watch_for = max(1, uniform(stay_time - 0.5, stay_time + 1))
            logger.info(f"Watching reel #{watched + 1} for ~{watch_for:.1f}s.")
            sleep(watch_for)

            watched += 1
            self.session_state.totalWatched += 1

            UniversalActions(device)._swipe_points(direction=Direction.UP, delta_y=800)
            random_sleep(inf=1, sup=2, modulable=False)

    def _is_reel_ad(self, device) -> tuple[bool, str]:
        # Reuse feed ad heuristics: sponsored root, ad badge, or localized labels
        sponsored_txts = [
            "sponsored",
            "gesponsert",
            "pubblicité",
            "publicidad",
            "sponsorisé",
            "advertisement",
            "ad",
        ]
        if device.find(
            resourceIdMatches=self.ResourceID.SPONSORED_CONTENT_SERVER_RENDERED_ROOT
        ).exists(Timeout.TINY):
            return True, "sponsored_root"
        ad_badge = device.find(resourceId=self.ResourceID.AD_BADGE)
        if ad_badge.exists(Timeout.TINY):
            return True, "ad_badge"
        label = device.find(textMatches=case_insensitive_re("|".join(sponsored_txts)))
        if label.exists(Timeout.TINY):
            return True, "label_text"
        desc_label = device.find(
            descriptionMatches=case_insensitive_re("|".join(sponsored_txts))
        )
        if desc_label.exists(Timeout.TINY):
            return True, "label_desc"
        return False, ""
