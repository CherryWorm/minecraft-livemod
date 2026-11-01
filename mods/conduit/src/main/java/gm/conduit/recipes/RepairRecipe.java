package gm.conduit.recipes;

import com.mojang.serialization.Codec;
import com.mojang.serialization.MapCodec;
import com.mojang.serialization.codecs.RecordCodecBuilder;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.crafting.CraftingInput;
import net.minecraft.world.item.crafting.CustomRecipe;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.PlacementInfo;
import net.minecraft.world.item.crafting.RecipeSerializer;
import net.minecraft.world.item.crafting.display.RecipeDisplay;
import net.minecraft.world.item.crafting.display.ShapelessCraftingRecipeDisplay;
import net.minecraft.world.item.crafting.display.SlotDisplay;
import net.minecraft.world.level.Level;

import java.util.List;

/** A worn tool and any amount of a material in a crafting grid give the tool back, mended by a share of its life for each one. It keeps all it had on it. */
public final class RepairRecipe extends CustomRecipe {
	static final MapCodec<RepairRecipe> CODEC = RecordCodecBuilder.mapCodec(fields -> fields.group(
			Ingredient.CODEC.fieldOf("tool").forGetter(recipe -> recipe.tool),
			Ingredient.CODEC.fieldOf("material").forGetter(recipe -> recipe.material),
			Codec.floatRange(0.0F, 1.0F).fieldOf("amount").forGetter(recipe -> recipe.amount)
	).apply(fields, RepairRecipe::new));
	static final RecipeSerializer<RepairRecipe> SERIALIZER = new RecipeSerializer<>(CODEC, SlotRecipes.neverSent());

	private final Ingredient tool;
	private final Ingredient material;
	private final float amount;

	private RepairRecipe(Ingredient tool, Ingredient material, float amount) {
		this.tool = tool;
		this.material = material;
		this.amount = amount;
	}

	/** The one worn tool in the grid, if everything else in it is what mends it and there's some of that. */
	private ItemStack toolIn(CraftingInput input) {
		ItemStack found = ItemStack.EMPTY;
		int materials = 0;
		for (ItemStack stack : input.items()) {
			if (stack.isEmpty()) {
				continue;
			}
			if (found.isEmpty() && this.tool.test(stack) && stack.isDamaged()) {
				found = stack;
			} else if (this.material.test(stack)) {
				materials++;
			} else {
				return ItemStack.EMPTY;
			}
		}
		return materials > 0 ? found : ItemStack.EMPTY;
	}

	@Override
	public boolean matches(CraftingInput input, Level level) {
		return !toolIn(input).isEmpty();
	}

	@Override
	public ItemStack assemble(CraftingInput input) {
		ItemStack worn = toolIn(input);
		if (worn.isEmpty()) {
			return ItemStack.EMPTY;
		}
		int materials = input.ingredientCount() - 1;
		ItemStack mended = worn.copyWithCount(1);
		mended.setDamageValue(Math.max(0, worn.getDamageValue() - Math.round(materials * this.amount * worn.getMaxDamage())));
		return mended;
	}

	/** A special recipe stays out of the recipe book and recipe viewers, and players need to be able to find this one. */
	@Override
	public boolean isSpecial() {
		return false;
	}

	@Override
	public PlacementInfo placementInfo() {
		return PlacementInfo.create(List.of(this.tool, this.material));
	}

	@Override
	public List<RecipeDisplay> display() {
		return List.of(new ShapelessCraftingRecipeDisplay(List.of(this.tool.display(), this.material.display()), this.tool.display(), new SlotDisplay.ItemSlotDisplay(Items.CRAFTING_TABLE)));
	}

	@Override
	public RecipeSerializer<RepairRecipe> getSerializer() {
		return SERIALIZER;
	}
}
