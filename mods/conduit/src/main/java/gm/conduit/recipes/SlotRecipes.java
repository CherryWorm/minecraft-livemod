package gm.conduit.recipes;

import eu.pb4.polymer.core.api.utils.PolymerSyncedObject;
import gm.conduit.Conduit;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.resources.Identifier;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.RecipeSerializer;

/** The two kinds of recipe a release can use that vanilla hasn't got. They only ever run on the server, so a client needs to know nothing about them. */
public final class SlotRecipes {
	private SlotRecipes() {}

	public static void register() {
		serializer("carry", CarryRecipe.SERIALIZER);
		serializer("repair", RepairRecipe.SERIALIZER);
	}

	private static void serializer(String name, RecipeSerializer<?> serializer) {
		Registry.register(BuiltInRegistries.RECIPE_SERIALIZER, Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, name), serializer);
		PolymerSyncedObject.setSyncedObject(BuiltInRegistries.RECIPE_SERIALIZER, serializer, (found, context) -> null);
	}

	/** The game no longer sends crafting recipes to anyone, and it only wants this to be there. */
	static <T extends Recipe<?>> StreamCodec<RegistryFriendlyByteBuf, T> neverSent() {
		return StreamCodec.of((buffer, recipe) -> {
			throw new UnsupportedOperationException("This recipe stays on the server");
		}, buffer -> {
			throw new UnsupportedOperationException("This recipe stays on the server");
		});
	}
}
