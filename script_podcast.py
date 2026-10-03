"""Compatibility entry point; all inference uses the approved worker."""
import sys
from worker import main
if __name__ == "__main__":
    sys.argv = [sys.argv[0], 'podcasts']
    main()
