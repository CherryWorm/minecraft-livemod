package gm.conduit.api;

import net.minecraft.world.item.ItemStack;

import java.util.List;

/**
 * The answer when a player tries something in a machine.
 *
 * @param output what it makes, or empty if this isn't a recipe the player can use. If it makes several things, this is the first
 * @param closest how many inputs matched the nearest recipe, so a machine can react to a near miss
 * @param needed how many inputs that nearest recipe takes
 * @param locked true if this is exactly a recipe they haven't learned yet
 * @param outputs everything it makes, or nothing if this isn't a recipe the player can use
 * @param recipe which recipe this is, as {@code feature/name}, or null if it isn't one
 * @param takes how much of each input the recipe uses up, or nothing if this isn't one
 * @param cells for a recipe with a shape, which places in the grid it uses one from, or nothing for one without
 */
public record MachineAttempt(ItemStack output, int closest, int needed, boolean locked, List<ItemStack> outputs, String recipe, List<ItemStack> takes, List<Integer> cells) {
	public boolean succeeded() {
		return !this.output.isEmpty();
	}

	public boolean nearMiss() {
		return !succeeded() && this.closest > 0;
	}

	/** Takes what the recipe uses from these stacks, so a machine doesn't need its own table of how much that is. */
	public void consume(List<ItemStack> inputs) {
		if (!this.cells.isEmpty()) {
			this.cells.forEach(cell -> inputs.get(cell).shrink(1));
			return;
		}
		for (ItemStack wanted : this.takes) {
			for (ItemStack stack : inputs) {
				if (stack.is(wanted.getItem()) && stack.getCount() >= wanted.getCount()) {
					stack.shrink(wanted.getCount());
					break;
				}
			}
		}
	}
}
