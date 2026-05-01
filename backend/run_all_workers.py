from dotenv import load_dotenv
load_dotenv()

import logging
import traceback
logging.basicConfig(level=logging.INFO)

workers = [
    ("broadcast_worker", "app.workers.broadcast_worker", "run_broadcast_dispatcher"),
    ("nps_worker",       "app.workers.nps_worker",       "run_nps_scheduler"),
    ("drip_worker",      "app.workers.drip_worker",      "run_drip_scheduler"),
    ("renewal_worker",   "app.workers.renewal_worker",   "send_renewal_reminders"),
    ("churn_worker",     "app.workers.churn_worker",     "run_daily_churn_scoring"),
    ("meta_token_worker","app.workers.meta_token_worker","run_meta_token_check"),
    ("shopify_sync",     "app.workers.shopify_sync_worker","sync_all_orgs"),
    ("cart_abandonment", "app.workers.cart_abandonment_worker","run_cart_abandonment_check"),
]

for name, module_path, fn_name in workers:
    print(f"\n{'='*50}")
    print(f"Running: {name}")
    try:
        import importlib
        mod = importlib.import_module(module_path)
        fn = getattr(mod, fn_name)
        # Call without Celery binding — pass a mock self for bind=True tasks
        try:
            result = fn()
        except TypeError:
            # bind=True tasks need self — create a minimal mock
            class FakeSelf:
                def retry(self, exc=None, countdown=0):
                    raise exc
            result = fn(FakeSelf())
        print(f"Result: {result}")
    except Exception as e:
        print(f"FAILED: {e}")
        traceback.print_exc()
