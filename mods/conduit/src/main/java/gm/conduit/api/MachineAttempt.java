package gm.conduit.api;

import net.minecraft.world.item.ItemStack;

/**
 * The answer when a player tries something in a machine.
 *
 * @param output what it makes, or empty if this isn't a recipe the player can use
 * @param closest how many inputs matched the nearest recipe, so a machine can react to a near miss
 * @param needed how many inputs that nearest recipe takes
 * @param locked true if this is exactly a recipe they haven't learned yet
 */
public record MachineAttempt(ItemStack output, int closest, int needed, boolean locked) {
	public boolean succeeded() {
		return !this.output.isEmpty();
	}

	public boolean nearMiss() {
		return !succeeded() && this.closest > 0;
	}
}
