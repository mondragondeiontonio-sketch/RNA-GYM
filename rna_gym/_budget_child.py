"""Linux child lifetime bound: die on supervisor death and independent wall alarm."""
import ctypes
import os
import signal
import sys

if __name__=="__main__":
    parent=int(sys.argv[1]); seconds=float(sys.argv[2]); command=sys.argv[3:]
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0: raise OSError(ctypes.get_errno(),"PR_SET_PDEATHSIG failed")
    if os.getppid()!=parent: raise SystemExit(125)
    os.environ["RNA_GYM_SUPERVISED_PID"]=str(os.getpid())
    signal.setitimer(signal.ITIMER_REAL,seconds)
    os.execvpe(command[0],command,os.environ)
