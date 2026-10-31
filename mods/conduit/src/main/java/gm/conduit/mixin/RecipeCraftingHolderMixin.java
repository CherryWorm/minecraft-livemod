package gm.conduit.mixin;

import gm.conduit.knowledge.Knowledge;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.inventory.RecipeCraftingHolder;
import net.minecraft.world.item.crafting.RecipeHolder;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Every crafting grid asks this before showing a result, so a recipe not yet learned shows nothing. */
@Mixin(RecipeCraftingHolder.class)
public interface RecipeCraftingHolderMixin {
	@Inject(method = "setRecipeUsed(Lnet/minecraft/server/level/ServerPlayer;Lnet/minecraft/world/item/crafting/RecipeHolder;)Z", at = @At("HEAD"), cancellable = true)
	private void conduit$onlyLearnedRecipes(ServerPlayer player, RecipeHolder<?> recipe, CallbackInfoReturnable<Boolean> info) {
		if (!Knowledge.instance().canUse(player, recipe.id().identifier())) {
			info.setReturnValue(false);
		}
	}
}
