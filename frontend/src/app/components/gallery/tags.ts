import tagList from '../../../../../shared/tags.json';

export type TagGroup = 'foe' | 'friend' | 'either';

const GROUP_BY_TAGS_JSON_GROUP: Record<string, TagGroup> = {
  pest: 'foe',
  pet: 'friend',
  'pest or pet': 'either',
};

export const TAG_GROUP = new Map<string, TagGroup>(
  tagList.tags.map((tag) => [tag.name, GROUP_BY_TAGS_JSON_GROUP[tag.group]]),
);

export const TAG_NAMES = tagList.tags.map((tag) => tag.name);
