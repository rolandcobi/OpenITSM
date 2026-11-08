"""Explicit chat/workspace registration using per-instance scoped dependencies."""
import chat
import space

def register(runtime):
    runtime._chat = chat
    runtime._space = space
    chat.init(runtime.app,runtime._D)
    space.init(runtime.app,runtime._D)
    runtime.space_summary_ = runtime._D['space_summary']
