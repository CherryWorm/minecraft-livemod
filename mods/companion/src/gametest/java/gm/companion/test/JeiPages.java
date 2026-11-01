package gm.companion.test;

import com.google.gson.Gson;
import gm.companion.jei.CompanionJeiPlugin;
import mezz.jei.api.constants.VanillaTypes;
import mezz.jei.api.recipe.IFocusGroup;
import mezz.jei.api.recipe.IRecipeManager;
import mezz.jei.api.recipe.RecipeIngredientRole;
import mezz.jei.api.recipe.category.IRecipeCategory;
import mezz.jei.api.runtime.IJeiRuntime;
import net.minecraft.core.component.DataComponents;
import net.minecraft.network.chat.Component;
import net.minecraft.world.item.ItemStack;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * What JEI really shows, read from JEI, for broker/tests/m23_test.py. A class of its own so that it only loads when a test
 * has JEI installed. An item is written as its model, because that's all that tells this world's items apart on a client.
 */
final class JeiPages {
	private static final String STAND_IN = "minecraft:trial_key";

	private JeiPages() {}

	/** Every page JEI has, as how many recipes it shows and every slot of each one that has anything from this world or a bare stand-in. */
	static String everySlot() {
		IJeiRuntime runtime = CompanionJeiPlugin.runtime();
		IRecipeManager recipes = runtime.getRecipeManager();
		IFocusGroup noFocus = runtime.getJeiHelpers().getFocusFactory().getEmptyFocusGroup();
		Map<String, Map<String, Object>> pages = new TreeMap<>();
		recipes.createRecipeCategoryLookup().get().forEach(category -> pages.put(category.getRecipeType().getUid().toString(), page(recipes, category, noFocus)));
		return new Gson().toJson(pages);
	}

	private static <T> Map<String, Object> page(IRecipeManager recipes, IRecipeCategory<T> category, IFocusGroup noFocus) {
		List<T> shown = recipes.createRecipeLookup(category.getRecipeType()).get().toList();
		List<List<List<String>>> ours = new ArrayList<>();
		for (T recipe : shown) {
			recipes.createRecipeLayoutDrawable(category, recipe, noFocus).ifPresent(layout -> {
				// All of a slot's alternatives, after JEI has worked out what it cycles through.
				List<List<String>> slots = layout.getRecipeSlotsView().getSlotViews().stream().map(slot -> slot.getItemStacks().map(JeiPages::model).toList()).toList();
				if (slots.stream().flatMap(List::stream).anyMatch(JeiPages::concerned)) {
					ours.add(slots);
				}
			});
		}
		return Map.of("recipes", shown.size(), "ours", ours);
	}

	private static String model(ItemStack stack) {
		return String.valueOf(stack.get(DataComponents.ITEM_MODEL));
	}

	private static boolean concerned(String model) {
		return model.equals(STAND_IN) || model.startsWith("gm:");
	}

	/** The mod JEI puts at the bottom of this stack's tooltip. */
	static String modOf(ItemStack stack) {
		IJeiRuntime runtime = CompanionJeiPlugin.runtime();
		return runtime.getIngredientManager().createTypedIngredient(VanillaTypes.ITEM_STACK, stack, true)
				.flatMap(typed -> runtime.getJeiHelpers().getModIdHelper().getModNameForTooltip(typed))
				.map(Component::getString).orElse("nothing");
	}

	/** Opens what JEI shows for this stack's uses, the way pressing U on it would. */
	static void showUses(ItemStack stack) {
		IJeiRuntime runtime = CompanionJeiPlugin.runtime();
		runtime.getRecipesGui().show(runtime.getJeiHelpers().getFocusFactory().createFocus(RecipeIngredientRole.INPUT, VanillaTypes.ITEM_STACK, stack));
	}
}
