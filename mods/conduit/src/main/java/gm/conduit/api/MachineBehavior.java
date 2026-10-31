package gm.conduit.api;

import gm.conduit.slots.SlotBlockEntity;

/** What a machine does each tick. Keep state in {@link SlotBlockEntity#data()} so it survives module swaps. */
public interface MachineBehavior {
	void tick(SlotBlockEntity machine);
}
