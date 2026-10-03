"""Process address-space ceiling also works on hosts without memory cgroups."""
import os
import resource
import sys

ceiling=int(os.getenv('MEMORY_CEILING_MB','1536'))*1024*1024
resource.setrlimit(resource.RLIMIT_AS,(ceiling,ceiling))
os.execvp(sys.argv[1],sys.argv[1:])
