package gm.companion.guide;

import gm.companion.KnownRecipes;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.renderer.RenderPipelines;
import net.minecraft.network.chat.Component;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import vazkii.patchouli.client.base.ClientTicker;
import vazkii.patchouli.client.book.BookContentsBuilder;
import vazkii.patchouli.client.book.BookEntry;
import vazkii.patchouli.client.book.BookPage;
import vazkii.patchouli.client.book.gui.GuiBook;
import vazkii.patchouli.common.book.Book;

import java.util.List;
import java.util.Objects;

/**
 * A page of recipes, drawn the way Patchouli draws its own. Those read recipes from the player's game, which has none of this world's, so
 * this reads what the server has told it they know, which also covers machines. One it hasn't been told about doesn't show.
 */
public final class KnownRecipePage extends BookPage {
	private static final int RECIPE_HEIGHT = 78;
	private static final int TOP = 4;
	private static final int LEFT = GuiBook.PAGE_WIDTH / 2 - 49;
	private static final int SLOT = 19;
	private static final int COLUMNS = 3;
	private static final int MOST_INPUTS = COLUMNS * COLUMNS;
	private static final int OUTPUT_X = 79;
	private static final int OUTPUT_Y = 22;
	private static final int ANY_ORDER_X = 62;
	private static final int ANY_ORDER_Y = 2;
	private static final int ANY_ORDER_SIZE = 11;
	private static final int STATION_Y = 62;

	List<String> recipes = List.of();
	private transient List<KnownRecipes.Shown> shown = List.of();

	@Override
	public boolean canAdd(Book book) {
		return super.canAdd(book) && !known().isEmpty();
	}

	@Override
	public void build(Level level, BookEntry entry, BookContentsBuilder builder, int pageNum) {
		super.build(level, entry, builder, pageNum);
		this.shown = known();
	}

	private List<KnownRecipes.Shown> known() {
		return this.recipes.stream().map(KnownRecipes::find).filter(Objects::nonNull).toList();
	}

	@Override
	public void extractRenderState(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float pticks) {
		for (int index = 0; index < this.shown.size(); index++) {
			draw(graphics, this.shown.get(index), TOP + index * RECIPE_HEIGHT, mouseX, mouseY);
		}
	}

	private void draw(GuiGraphicsExtractor graphics, KnownRecipes.Shown recipe, int top, int mouseX, int mouseY) {
		graphics.blit(RenderPipelines.GUI_TEXTURED, this.book.craftingTexture, LEFT - 2, top - 2, 0, 0, 100, 62, 128, 256, 0xffffffff);
		this.parent.drawCenteredStringNoShadow(graphics, recipe.output().getHoverName().getVisualOrderText(), GuiBook.PAGE_WIDTH / 2, top - 10, this.book.headerColor);
		if (recipe.width() == 0) {
			graphics.blit(RenderPipelines.GUI_TEXTURED, this.book.craftingTexture, LEFT + ANY_ORDER_X, top + ANY_ORDER_Y, 0, 64, ANY_ORDER_SIZE, ANY_ORDER_SIZE, 128, 256, 0xffffffff);
			if (this.parent.isMouseInRelativeRange(mouseX, mouseY, LEFT + ANY_ORDER_X, top + ANY_ORDER_Y, ANY_ORDER_SIZE, ANY_ORDER_SIZE)) {
				this.parent.setTooltip(Component.translatable("patchouli.gui.lexicon.shapeless"));
			}
		}

		int columns = recipe.width() > 0 ? recipe.width() : COLUMNS;
		int count = Math.min(recipe.inputs().size(), MOST_INPUTS);
		int rows = (count + columns - 1) / columns;
		int offsetX = (COLUMNS - columns) * SLOT / 2;
		int offsetY = (COLUMNS - rows) * SLOT / 2;
		for (int index = 0; index < count; index++) {
			List<ItemStack> choices = recipe.inputs().get(index);
			if (!choices.isEmpty()) {
				ItemStack stack = choices.get((int) (ClientTicker.ticksInGame / 20 % choices.size()));
				this.parent.renderItemStack(graphics, LEFT + offsetX + index % columns * SLOT + 3, top + offsetY + index / columns * SLOT + 3, mouseX, mouseY, stack);
			}
		}
		this.parent.renderItemStack(graphics, LEFT + OUTPUT_X, top + OUTPUT_Y, mouseX, mouseY, recipe.output());
		if (!recipe.station().isEmpty()) {
			this.parent.drawCenteredStringNoShadow(graphics, recipe.station(), GuiBook.PAGE_WIDTH / 2, top + STATION_Y, this.book.textColor);
		}
	}
}
