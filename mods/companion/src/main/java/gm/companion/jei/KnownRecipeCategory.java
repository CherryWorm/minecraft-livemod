package gm.companion.jei;

import gm.companion.KnownRecipes;
import mezz.jei.api.gui.builder.IRecipeLayoutBuilder;
import mezz.jei.api.gui.builder.IRecipeSlotBuilder;
import mezz.jei.api.gui.drawable.IDrawable;
import mezz.jei.api.gui.widgets.IRecipeExtrasBuilder;
import mezz.jei.api.helpers.IGuiHelper;
import mezz.jei.api.recipe.IFocusGroup;
import mezz.jei.api.recipe.RecipeIngredientRole;
import mezz.jei.api.recipe.category.IRecipeCategory;
import mezz.jei.api.recipe.types.IRecipeType;
import net.minecraft.network.chat.Component;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

import java.util.List;

/** One page for everything from this world, whatever it's made at: its inputs in a grid, what it makes, and where. */
final class KnownRecipeCategory implements IRecipeCategory<KnownRecipes.Shown> {
	static final IRecipeType<KnownRecipes.Shown> TYPE = IRecipeType.create("gm", "known_recipes", KnownRecipes.Shown.class);
	private static final int WIDTH = 120;
	private static final int HEIGHT = 66;
	private static final int SLOT = 18;
	private static final int MOST_COLUMNS = 3;
	private static final int MOST_INPUTS = 9;

	private final IDrawable icon;

	KnownRecipeCategory(IGuiHelper guiHelper) {
		this.icon = guiHelper.createDrawableItemStack(new ItemStack(Items.KNOWLEDGE_BOOK));
	}

	@Override
	public IRecipeType<KnownRecipes.Shown> getRecipeType() {
		return TYPE;
	}

	@Override
	public Component getTitle() {
		return Component.literal("Recipes you know");
	}

	@Override
	public int getWidth() {
		return WIDTH;
	}

	@Override
	public int getHeight() {
		return HEIGHT;
	}

	@Override
	public IDrawable getIcon() {
		return this.icon;
	}

	@Override
	public void setRecipe(IRecipeLayoutBuilder builder, KnownRecipes.Shown recipe, IFocusGroup focuses) {
		int columns = recipe.width() > 0 ? recipe.width() : MOST_COLUMNS;
		List<List<ItemStack>> inputs = recipe.inputs();
		for (int index = 0; index < Math.min(inputs.size(), MOST_INPUTS); index++) {
			IRecipeSlotBuilder slot = builder.addSlot(RecipeIngredientRole.INPUT, index % columns * SLOT, index / columns * SLOT).setStandardSlotBackground();
			if (!inputs.get(index).isEmpty()) {
				slot.addItemStacks(inputs.get(index));
			}
		}
		if (recipe.width() == 0) {
			builder.setShapeless();
		}
		builder.addSlot(RecipeIngredientRole.OUTPUT, 96, SLOT).setStandardSlotBackground().addItemStack(recipe.output());
	}

	@Override
	public void createRecipeExtras(IRecipeExtrasBuilder extras, KnownRecipes.Shown recipe, IFocusGroup focuses) {
		extras.addRecipeArrow().setPosition(62, SLOT);
		if (!recipe.station().isEmpty()) {
			extras.addText(Component.literal(recipe.station()), WIDTH, 10).setPosition(0, 56);
		}
	}
}
