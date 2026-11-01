package gm.conduit.slots;

import net.minecraft.core.component.DataComponents;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.CustomData;

/**
 * The bar under an item in a client's inventory, for something that isn't a tool: a charge, say. It's only drawn with a tool's durability, because that's all a client can
 * draw, but it's only a tool to the client. To the game here it can't wear out, be mended or be enchanted for that, and it's not a number any tier has an opinion on.
 */
public final class ItemBars {
	public static final int STEPS = 1000;
	private static final String KEY = "gm_bar";

	private ItemBars() {}

	public static boolean hasBar(ItemStack stack) {
		CustomData data = stack.get(DataComponents.CUSTOM_DATA);
		return data != null && data.copyTag().contains(KEY);
	}

	public static float fraction(ItemStack stack) {
		CustomData data = stack.get(DataComponents.CUSTOM_DATA);
		return data == null ? 0.0F : data.copyTag().getFloatOr(KEY, 0.0F);
	}

	public static void set(ItemStack stack, float fraction) {
		CustomData.update(DataComponents.CUSTOM_DATA, stack, tag -> tag.putFloat(KEY, Math.clamp(fraction, 0.0F, 1.0F)));
	}

	/** A client doesn't draw the bar at all with no damage, so a full one is the least damage there can be. */
	static int damageShown(ItemStack stack) {
		return Math.clamp(Math.round((1.0F - fraction(stack)) * STEPS), 1, STEPS);
	}
}
