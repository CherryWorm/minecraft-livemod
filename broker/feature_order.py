"""Keeps biomes agreeing on what order their features run in.

Every biome lists its features in the order they run, and the game refuses to start a world if two of its biomes disagree about which of
two features comes first, even through a chain of others. So a feature can't just go on the end of a biome's list. This goes by the same
rule the game does, in FeatureSorter: each feature, in the step it's listed under, follows the one before it, across every biome.
"""
STEPS = ("raw_generation", "lakes", "local_modifications", "underground_structures", "surface_structures", "strongholds",
         "underground_ores", "underground_decoration", "fluid_springs", "vegetal_decoration", "top_layer_modification")


class OrderError(Exception):
    """Worded for whoever wrote the biome."""


def _flattened(features):
    return [(step, feature) for step, listed in enumerate(features) for feature in listed]


class FeatureOrder:
    """Everything that has to come after what, across the biomes it's been told about, and what features there are to use."""

    def __init__(self, biomes=(), placed_features=()):
        self.after = {}
        self.placed_features = set(placed_features)
        for features in biomes:
            self._add_links(_flattened(features))

    def _add_links(self, flattened):
        for first, second in zip(flattened, flattened[1:]):
            self.after.setdefault(first, set()).add(second)

    def _clash_with(self, flattened):
        """Two features that would have to run in both orders if a biome had this list, or None. The game looks for just this, so it has to be all of it, not just this list."""
        after = {node: set(following) for node, following in self.after.items()}
        for first, second in zip(flattened, flattened[1:]):
            after.setdefault(first, set()).add(second)
        finished = set()
        for start in flattened:
            if start in finished:
                continue
            visiting = {start}
            path = [(start, iter(after.get(start, ())))]
            while path:
                node, following = path[-1]
                for next_node in following:
                    if next_node in visiting:
                        return node, next_node
                    if next_node not in finished:
                        visiting.add(next_node)
                        path.append((next_node, iter(after.get(next_node, ()))))
                        break
                else:
                    path.pop()
                    visiting.discard(node)
                    finished.add(node)
        return None

    def add_biome(self, name, features):
        """Takes on a biome's own list, or refuses it if the game would."""
        flattened = _flattened(features)
        repeated = next((node for index, node in enumerate(flattened) if node in flattened[:index]), None)
        if repeated:
            raise OrderError(f"{name} lists {repeated[1]} twice in {STEPS[repeated[0]]}, which the game refuses, because a feature can't come before itself.")
        clash = self._clash_with(flattened)
        if clash:
            raise OrderError(f"{name} would have {clash[0][1]} run before {clash[1][1]}, and another biome has them the other way round, directly or through others, "
                             "so the game wouldn't start. Use add_features, which finds a place for each one that works.")
        self._add_links(flattened)

    def place(self, name, features, step, feature):
        """Returns the features with this one put in the last place in its step that every biome can agree with."""
        index = STEPS.index(step)
        listed = features[index]
        if feature in listed:
            raise OrderError(f"{name} already has {feature} in {step}.")
        for position in range(len(listed), -1, -1):
            trial = [*features[:index], [*listed[:position], feature, *listed[position:]], *features[index + 1:]]
            if self._clash_with(_flattened(trial)) is None:
                return trial
        raise OrderError(f"There's nowhere in {name}'s {step} that {feature} can go without two biomes disagreeing about the order, so the game wouldn't start.")
