package gm.conduit.api;

import gm.conduit.slots.SlotBlockEntity;

/** What a machine does each tick. Keep state in {@link SlotBlockEntity#data()} so it survives module swaps. */
public interface MachineBehavior {
	void tick(SlotBlockEntity machine);

	/**
	 * The machine is about to go and {@link SlotBlockEntity#data()} is still there, so this is where it drops what it holds.
	 * A command replacing it doesn't count, in the same way a chest's contents don't drop then.
	 */
	default void removed(SlotBlockEntity machine) {}
}
