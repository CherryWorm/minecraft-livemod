package gm.conduit.api;

import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.world.item.ItemStack;

/** What a machine does each tick. Keep state in {@link SlotBlockEntity#data()} so it survives module swaps. */
public interface MachineBehavior {
	void tick(SlotBlockEntity machine);

	/**
	 * The machine is about to go and {@link SlotBlockEntity#data()} is still there, so this is where it drops what it holds.
	 * A command replacing it doesn't count, in the same way a chest's contents don't drop then. Its inventory drops by itself.
	 */
	default void removed(SlotBlockEntity machine) {}

	/** Whether this can go in one of its input or fuel slots, from a hopper or a player. Nothing can be put in an output slot. */
	default boolean accepts(SlotBlockEntity machine, int slot, ItemStack stack) {
		return true;
	}
}
