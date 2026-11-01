package gm.conduit.mixin;

import eu.pb4.polymer.core.api.item.PolymerItem;
import net.minecraft.core.HolderSet;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.display.SlotDisplay;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * The game shows an ingredient as one list of items, and Polymer sends that list as it is, plus a proper picture of each of ours.
 * To a client the list's entry for one of ours is only the stand-in, a plain trial key, so a recipe viewer cycles between the item and
 * that. Listing them one by one lets Polymer replace each one, which leaves only the pictures.
 */
@Mixin(Ingredient.class)
public abstract class IngredientMixin {
	@Shadow
	@Final
	private HolderSet<Item> values;

	@Inject(method = "display", at = @At("HEAD"), cancellable = true)
	private void conduit$listOursOneByOne(CallbackInfoReturnable<SlotDisplay> info) {
		if (this.values.unwrapKey().isEmpty() && this.values.stream().anyMatch(item -> item.value() instanceof PolymerItem)) {
			info.setReturnValue(new SlotDisplay.Composite(this.values.stream().<SlotDisplay>map(SlotDisplay.ItemSlotDisplay::new).toList()));
		}
	}
}
