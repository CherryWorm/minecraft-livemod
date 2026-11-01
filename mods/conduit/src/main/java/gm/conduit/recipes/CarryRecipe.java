package gm.conduit.recipes;

import com.mojang.serialization.Codec;
import com.mojang.serialization.DataResult;
import com.mojang.serialization.MapCodec;
import com.mojang.serialization.codecs.RecordCodecBuilder;
import net.minecraft.core.NonNullList;
import net.minecraft.core.component.DataComponents;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.CraftingBookCategory;
import net.minecraft.world.item.crafting.CraftingInput;
import net.minecraft.world.item.crafting.CraftingRecipe;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.PlacementInfo;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.RecipeSerializer;
import net.minecraft.world.item.crafting.display.RecipeDisplay;
import net.minecraft.world.level.Level;

import java.util.List;

/**
 * An ordinary crafting recipe, whose result takes something after one of its inputs: how worn it was, its enchantments, or its data. So upgrading a
 * tool doesn't mend it or lose what's on it. Only those can come across, because anything like a tool's numbers belongs to what's being made.
 */
public final class CarryRecipe implements CraftingRecipe {
	private static final String WEAR = "wear";
	private static final String ENCHANTMENTS = "enchantments";
	private static final String DATA = "data";
	private static final Codec<CraftingRecipe> CRAFTING = Recipe.DIRECT_CODEC.comapFlatMap(
			recipe -> recipe instanceof CraftingRecipe crafting ? DataResult.success(crafting) : DataResult.error(() -> "Only a crafting recipe can carry anything across"),
			recipe -> recipe);
	static final MapCodec<CarryRecipe> CODEC = RecordCodecBuilder.mapCodec(fields -> fields.group(
			CRAFTING.fieldOf("recipe").forGetter(recipe -> recipe.inner),
			Ingredient.CODEC.fieldOf("from").forGetter(recipe -> recipe.from),
			Codec.STRING.listOf().fieldOf("what").forGetter(recipe -> recipe.what)
	).apply(fields, CarryRecipe::new));
	static final RecipeSerializer<CarryRecipe> SERIALIZER = new RecipeSerializer<>(CODEC, SlotRecipes.neverSent());

	private final CraftingRecipe inner;
	private final Ingredient from;
	private final List<String> what;

	private CarryRecipe(CraftingRecipe inner, Ingredient from, List<String> what) {
		this.inner = inner;
		this.from = from;
		this.what = what;
	}

	@Override
	public ItemStack assemble(CraftingInput input) {
		ItemStack made = this.inner.assemble(input);
		for (ItemStack stack : input.items()) {
			if (!stack.isEmpty() && this.from.test(stack)) {
				carry(stack, made);
				break;
			}
		}
		return made;
	}

	private void carry(ItemStack old, ItemStack made) {
		if (this.what.contains(WEAR) && old.isDamageableItem() && made.isDamageableItem()) {
			// By how far through its life it was, because the two may not last equally long.
			made.setDamageValue(Math.round((float) old.getDamageValue() / old.getMaxDamage() * made.getMaxDamage()));
		}
		if (this.what.contains(ENCHANTMENTS)) {
			made.copyFrom(DataComponents.ENCHANTMENTS, old);
			made.copyFrom(DataComponents.STORED_ENCHANTMENTS, old);
		}
		if (this.what.contains(DATA)) {
			made.copyFrom(DataComponents.CUSTOM_DATA, old);
			made.copyFrom(DataComponents.CUSTOM_NAME, old);
		}
	}

	@Override
	public boolean matches(CraftingInput input, Level level) {
		return this.inner.matches(input, level);
	}

	@Override
	public NonNullList<ItemStack> getRemainingItems(CraftingInput input) {
		return this.inner.getRemainingItems(input);
	}

	@Override
	public boolean isSpecial() {
		return this.inner.isSpecial();
	}

	@Override
	public boolean showNotification() {
		return this.inner.showNotification();
	}

	@Override
	public String group() {
		return this.inner.group();
	}

	@Override
	public RecipeSerializer<CarryRecipe> getSerializer() {
		return SERIALIZER;
	}

	@Override
	public PlacementInfo placementInfo() {
		return this.inner.placementInfo();
	}

	@Override
	public List<RecipeDisplay> display() {
		return this.inner.display();
	}

	@Override
	public CraftingBookCategory category() {
		return this.inner.category();
	}
}
