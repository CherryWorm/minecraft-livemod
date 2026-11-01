package gm.conduit.mixin;

import net.fabricmc.fabric.impl.recipe.sync.RecipeSyncImpl;
import net.fabricmc.fabric.impl.recipe.sync.SyncedSerializerAwarePreparedRecipe;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.RecipeSerializer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Redirect;

import java.util.List;

/**
 * JEI on the server has Fabric send every recipe to every client that has JEI. A recipe can only tell a client about one of ours as
 * its stand-in, which JEI takes to mean any trial key at all, and it would show all of this world's recipes whether the player had
 * earned them or not. KnownRecipes sends each player what they know, with the real items, so only vanilla's recipes go this way.
 */
@Mixin(RecipeSyncImpl.class)
public abstract class RecipeSyncImplMixin {
	@Redirect(method = "sendRecipes", at = @At(value = "INVOKE", target = "Lnet/fabricmc/fabric/impl/recipe/sync/SyncedSerializerAwarePreparedRecipe;fabric_getRecipesBySyncedSerializer(Lnet/minecraft/world/item/crafting/RecipeSerializer;)Ljava/util/List;"))
	private static List<RecipeHolder<?>> conduit$onlyVanillas(SyncedSerializerAwarePreparedRecipe recipes, RecipeSerializer<?> serializer) {
		List<RecipeHolder<?>> all = recipes.fabric_getRecipesBySyncedSerializer(serializer);
		return all == null ? null : all.stream().filter(recipe -> !recipe.id().identifier().getNamespace().equals("gm")).toList();
	}
}
