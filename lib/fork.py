import cPickle
import os
import signal

def register_sighandler():
     signal.signal(signal.SIGTERM, termsignal)
     signal.signal(signal.SIGQUIT, termsignal)

def unregister_sighandler():
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGQUIT, signal.SIG_DFL)

def termsignal(signr, frame):
    raise KeyboardInterrupt, "Received signal %s" % signr

def fork_in_bg(function, *args):
    # fork and call a function with args
    #  return a dict with {'r': fd, 'pid': pid} where fd is the stdout from a pipe.
    #    example:
    #      def add(i, j): return i+j
    #      d = fork_in_bg(add, i, j)

    r, w = os.pipe()
    unregister_sighandler()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        try:
            out = function(*args)
            os.write(w, cPickle.dumps(out))
        finally:
            os.close(w)
            os._exit(0)
    else:
        register_sighandler()
        os.close(w)

    return {'r': r, 'pid': pid}
