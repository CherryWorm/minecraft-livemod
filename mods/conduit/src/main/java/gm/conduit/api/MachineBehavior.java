package gm.conduit.api;

import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.world.entity.player.Player;
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

	/** How many fit in this slot right now. It can only make it less than {@code limit}, which is what its feature says, so a machine's upgrades should start from its largest. */
	default int slotLimit(SlotBlockEntity machine, int slot, int limit) {
		return limit;
	}

	/** Whether a player can take from this output slot, for a machine that's still busy. A hopper doesn't ask. */
	default boolean canTake(SlotBlockEntity machine, int slot, Player player) {
		return true;
	}

	/**
	 * A player has just taken this from an output slot, by hand or with a shift-click, such as to give them experience the way a furnace does.
	 * A hopper emptying it doesn't count, in the same way it earns no experience from a furnace.
	 */
	default void outputTaken(SlotBlockEntity machine, int slot, ItemStack stack, Player player) {}
}
