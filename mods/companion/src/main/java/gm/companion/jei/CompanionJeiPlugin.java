package gm.companion.jei;

import gm.companion.KnownRecipes;
import mezz.jei.api.IModPlugin;
import mezz.jei.api.constants.VanillaTypes;
import mezz.jei.api.recipe.IFocus;
import mezz.jei.api.recipe.RecipeIngredientRole;
import mezz.jei.api.registration.IRecipeCategoryRegistration;
import mezz.jei.api.registration.ISubtypeRegistration;
import mezz.jei.api.runtime.IJeiRuntime;
import net.minecraft.client.Minecraft;
import net.minecraft.core.component.DataComponents;
import net.minecraft.resources.Identifier;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Shows this world's recipes in JEI, as far as the player knows them. JEI only loads this if it's installed. On the
 * player's machine, everything from this world is a stand-in vanilla item that only its model tells apart, so JEI has to
 * look at the model too, or asking about one would answer for all of them.
 */
public final class CompanionJeiPlugin implements IModPlugin {
	private static final Identifier ID = Identifier.fromNamespaceAndPath("gm", "known_recipes");
	private static final Map<String, KnownRecipes.Shown> ADDED = new HashMap<>();
	private static final Set<Identifier> LISTED = new HashSet<>();
	private static IJeiRuntime runtime;

	@Override
	public Identifier getPluginUid() {
		return ID;
	}

	@Override
	public void registerItemSubtypes(ISubtypeRegistration registration) {
		registration.registerFromDataComponentTypes(Items.TRIAL_KEY, DataComponents.ITEM_MODEL);
	}

	@Override
	public void registerCategories(IRecipeCategoryRegistration registration) {
		registration.addRecipeCategories(new KnownRecipeCategory(registration.getJeiHelpers().getGuiHelper()));
	}

	@Override
	public void onRuntimeAvailable(IJeiRuntime available) {
		Minecraft.getInstance().execute(() -> {
			runtime = available;
			ADDED.clear();
			LISTED.clear();
			KnownRecipes.onChange(CompanionJeiPlugin::sync);
			sync();
		});
	}

	@Override
	public void onRuntimeUnavailable() {
		Minecraft.getInstance().execute(() -> {
			runtime = null;
			KnownRecipes.onChange(() -> {});
		});
	}

	private static void sync() {
		if (runtime == null) {
			return;
		}
		Map<String, KnownRecipes.Shown> wanted = new HashMap<>();
		KnownRecipes.known().forEach(recipe -> wanted.put(recipe.id(), recipe));

		List<KnownRecipes.Shown> gone = ADDED.entrySet().stream().filter(entry -> !wanted.containsKey(entry.getKey())).map(Map.Entry::getValue).toList();
		if (!gone.isEmpty()) {
			runtime.getRecipeManager().hideRecipes(KnownRecipeCategory.TYPE, gone);
			gone.forEach(recipe -> ADDED.remove(recipe.id()));
		}
		List<KnownRecipes.Shown> fresh = wanted.values().stream().filter(recipe -> !ADDED.containsKey(recipe.id())).toList();
		if (!fresh.isEmpty()) {
			List<ItemStack> newItems = new ArrayList<>();
			for (KnownRecipes.Shown recipe : fresh) {
				list(recipe.output(), newItems);
				recipe.inputs().forEach(slot -> slot.forEach(stack -> list(stack, newItems)));
			}
			if (!newItems.isEmpty()) {
				runtime.getIngredientManager().addIngredientsAtRuntime(VanillaTypes.ITEM_STACK, newItems);
			}
			runtime.getRecipeManager().addRecipes(KnownRecipeCategory.TYPE, fresh);
			fresh.forEach(recipe -> ADDED.put(recipe.id(), recipe));
		}
	}

	/** Puts one of this world's items in JEI's own list, the first time it comes up. Vanilla's are already there. */
	private static void list(ItemStack stack, List<ItemStack> newItems) {
		Identifier model = stack.get(DataComponents.ITEM_MODEL);
		if (model != null && !model.getNamespace().equals(Identifier.DEFAULT_NAMESPACE) && LISTED.add(model)) {
			newItems.add(stack.copyWithCount(1));
		}
	}

	/** For tests: what JEI itself would show, for anything or for what makes one item. */
	public static List<String> shown(ItemStack makes) {
		if (runtime == null) {
			return List.of("JEI isn't running");
		}
		var lookup = runtime.getRecipeManager().createRecipeLookup(KnownRecipeCategory.TYPE);
		if (!makes.isEmpty()) {
			IFocus<ItemStack> focus = runtime.getJeiHelpers().getFocusFactory().createFocus(RecipeIngredientRole.OUTPUT, VanillaTypes.ITEM_STACK, makes);
			lookup = lookup.limitFocus(List.of(focus));
		}
		return lookup.get().map(recipe -> recipe.output().getHoverName().getString() + " at " + recipe.station()).sorted().toList();
	}

	/** For tests: opens the page, the way a player would by clicking the category. */
	public static void showPage() {
		if (runtime != null) {
			runtime.getRecipesGui().showTypes(List.of(KnownRecipeCategory.TYPE));
		}
	}

	/** For tests: JEI itself, to read what it really shows, or null if it isn't running. */
	public static IJeiRuntime runtime() {
		return runtime;
	}
}
